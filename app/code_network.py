"""Administrator-controlled public TCP proxy policy, checked for every connection.
The internal Docker network remains isolated; this never changes browser policy.
"""

import ipaddress, json, re

DEFAULT_HOSTS = (
    "registry.npmjs.org",
    "registry.yarnpkg.com",
    "pypi.org",
    "files.pythonhosted.org",
    "crates.io",
    "index.crates.io",
    "static.crates.io",
    "proxy.golang.org",
    "sum.golang.org",
    "storage.googleapis.com",
    "repo.maven.apache.org",
    "rubygems.org",
    "index.rubygems.org",
    "packagist.org",
    "repo.packagist.org",
    "github.com",
    "codeload.github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)


def defaults():
    return {"rules": [{"destination": h, "ports": [443]} for h in DEFAULT_HOSTS]}


def public_ip(value):
    ip = ipaddress.ip_address(value)
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and (
        ip.ipv4_mapped
        or ip.sixtofour
        or ip.teredo
        or ip in ipaddress.ip_network("64:ff9b::/96")
    ):
        return False
    return True


def normalize_destination(value):
    if not isinstance(value, str):
        raise ValueError("Destination must be a domain, IP address or subnet")
    value = value.strip().lower().rstrip(".")
    try:
        network = ipaddress.ip_network(value, strict=False)
        if not public_ip(network.network_address) or not public_ip(
            network.broadcast_address
        ):
            raise ValueError("Only public internet addresses may be allowed")
        return str(network) if "/" in value else str(network.network_address)
    except ValueError:
        if "/" in value or ":" in value or re.fullmatch(r"[\d.]+", value):
            raise ValueError(
                "Only valid public IP addresses and subnets may be allowed"
            )
    wildcard = value.startswith("*.")
    domain = value[2:] if wildcard else value
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("Invalid domain")
    if (
        len(domain) > 253
        or "." not in domain
        or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", p)
            for p in domain.split(".")
        )
    ):
        raise ValueError(
            "Use a domain without a scheme/path, optionally starting with *."
        )
    if domain.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Only public domains may be allowed")
    return ("*." if wildcard else "") + domain


def validate(policy, account=False):
    keys = {"rules", "inherit", "unrestricted"} if account else {"rules"}
    if not isinstance(policy, dict) or set(policy) != keys:
        raise ValueError("Invalid coding network policy")
    if account and (
        type(policy["inherit"]) != bool or type(policy["unrestricted"]) != bool
    ):
        raise ValueError("Invalid network inheritance or access mode")
    if not isinstance(policy["rules"], list) or len(policy["rules"]) > 200:
        raise ValueError("Use at most 200 network rules")
    rules = []
    seen = set()
    for rule in policy["rules"]:
        if not isinstance(rule, dict) or set(rule) != {"destination", "ports"}:
            raise ValueError("Each rule needs a destination and ports")
        dest = normalize_destination(rule["destination"])
        ports = rule["ports"]
        if ports != "*":
            if (
                not isinstance(ports, list)
                or not 1 <= len(ports) <= 50
                or any(type(p) != int or not 1 <= p <= 65535 for p in ports)
            ):
                raise ValueError(
                    "Ports must be * or a list of 1–50 ports between 1 and 65535"
                )
            ports = sorted(set(ports))
        key = (dest, str(ports))
        if key not in seen:
            rules.append({"destination": dest, "ports": ports})
            seen.add(key)
    return {**policy, "rules": rules}


def read(scope="global", c=None):
    from . import core

    if c is None:
        with core.db() as c:
            return read(scope, c)
    row = c.execute(
        "SELECT body,version FROM admin_settings WHERE id=%s",
        ("code-network:" + scope,),
    ).fetchone()
    return {
        "policy": (
            json.loads(row["body"])
            if row
            else (
                defaults()
                if scope == "global"
                else {"inherit": True, "unrestricted": False, "rules": []}
            )
        ),
        "version": row["version"] if row else 0,
    }


def effective(scope, c=None):
    from . import core

    if c is None:
        with core.db() as c:
            return effective(scope, c)
    global_ = read("global", c)
    account = read(scope, c) if scope != "global" else None
    p = (
        account["policy"]
        if account
        else {"inherit": True, "unrestricted": False, "rules": []}
    )
    return {
        "rules": (global_["policy"]["rules"] if p["inherit"] else []) + p["rules"],
        "unrestricted": p["unrestricted"],
        "source": (
            "global + account"
            if p["inherit"] and p["rules"]
            else "global" if p["inherit"] else "account"
        ),
    }


def save(actor, scope, policy, version):
    from . import core, accounts

    policy = validate(policy, scope != "global")
    if type(version) != int:
        raise ValueError("Network policy version is required")
    with core.db() as c:
        c.begin_write()
        accounts.guard_admin(c, actor)
        if (
            scope != "global"
            and not c.execute("SELECT id FROM users WHERE id=%s", (scope,)).fetchone()
        ):
            raise ValueError("Account not found")
        old = read(scope, c)
        if old["version"] != version:
            raise ValueError("Network policy changed elsewhere. Reload before saving.")
        c.execute(
            "INSERT INTO admin_settings VALUES(%s,%s,%s) ON CONFLICT(id) DO UPDATE SET body=excluded.body,version=excluded.version",
            ("code-network:" + scope, json.dumps(policy), version + 1),
        )
        accounts.audit(
            c,
            actor,
            scope,
            "code_network_updated",
            {"before": old["policy"], "after": policy},
        )
        c.commit()
    return read(scope)


def task_policy(task):
    from . import core, accounts

    with core.db() as c:
        row = c.execute(
            "SELECT owner,status FROM tasks WHERE id=%s", (task,)
        ).fetchone()
        if not row or row["status"] == "cancelled":
            raise ValueError("Workspace is unavailable")
        accounts.require(row["owner"], "code", c)
        # Installation checks always exercise the shipped restrictive default policy.
        if row["owner"] == "aster-installation-checks":
            return {**defaults(), "unrestricted": False}
        return effective(row["owner"], c)


def permits(policy, host, ip, port):
    if not public_ip(ip):
        return False
    if policy.get("unrestricted"):
        return True
    for rule in policy["rules"]:
        if rule["ports"] != "*" and port not in rule["ports"]:
            continue
        dest = rule["destination"]
        try:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(dest, strict=False):
                return True
        except ValueError:
            if host == dest or (
                dest.startswith("*.") and host.endswith(dest[1:]) and host != dest[2:]
            ):
                return True
    return False
