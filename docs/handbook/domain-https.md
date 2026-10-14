# Domains, HTTP and HTTPS

Choose localhost, a private IP or a hostname with optional TLS.

Applies to: Community

## No domain required

For a private deployment, enter the server IPv4 address and use HTTP. Choosing localhost binds only to loopback. The current installer accepts hostnames or IPv4 on standard ports; custom ports and reverse-proxy layouts need manual origin/proxy configuration.


## Use HTTPS for public access

HTTP carries credentials and content without transport encryption. Use it only on a trusted network or tunnel. For public use, configure a domain and enable HTTPS through the installer. Caddy manages the reverse-proxy configuration and certificate workflow.


## Origin consistency

Open the exact configured origin. The application validates write origins and CSRF tokens; changing scheme, host or port can cause legitimate requests to be rejected if the configuration is not updated accordingly.


## Localhost and remote access

The default localhost origin is http://localhost on port 80. A matching SSH tunnel must forward local port 80 to server port 80 and may require local administrator privileges. Opening a different local port without updating the configured origin is not equivalent.


## Existing web servers

The installer refuses to overwrite an unowned Caddy configuration. Use a dedicated host. In prepared-host mode, review and preserve an unused packaged default separately before proceeding; do not delete configuration serving other sites.


## Choose an access pattern

Localhost is useful when only a browser on the host or a controlled tunnel needs access. A private IPv4 address is useful on a trusted LAN or VPN. A public hostname with HTTPS is the appropriate path when users reach the service across an untrusted network. These choices affect where the listener is reachable and which origin the application accepts.

A domain and SSL certificate are optional for Community installation. That does not make plain HTTP encrypted. Anyone able to observe an unprotected network path may see credentials or content. Keep HTTP deployment inside a trusted boundary and do not publish it unintentionally through router forwarding.


## Diagnose a page that loads but cannot save

A static page loading establishes that the web server is reachable; it does not prove authenticated API requests are accepted. Compare the URL in the address bar with the configured application origin, including http versus https and the port. A hosts-file alias or another local forwarding port counts as a different origin.

Use the configured URL first. Do not remove Origin or CSRF checks as a workaround. If you deliberately change the public address, update the site/proxy configuration consistently and retest sign-in and a harmless settings change before asking members to use the new address.


## Check DNS and TLS in order

1. Confirm the hostname resolves to the intended host and that the network permits the required web traffic.
2. Ensure no unrelated web server owns the same ports. The installer protects an unowned Caddy configuration rather than overwriting it.
3. Use the installer’s HTTPS path and inspect Caddy logs if certificate provisioning fails.
4. Open the exact configured HTTPS origin and verify the browser accepts its certificate.
5. Test sign-in, a harmless write and a workspace connection. A successful static page alone is not an end-to-end check.

## Keep internal services internal

Only the intended web entry point should be exposed. PostgreSQL, the application’s direct port 8000 and the broker’s port 8091 are internal services. The privileged broker is especially sensitive because it provisions execution environments. Do not make these ports public to work around a proxy error.

