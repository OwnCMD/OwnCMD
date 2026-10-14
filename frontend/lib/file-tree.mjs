// Preserve exact relative paths; folder presentation never changes file identity.
export function fileTree(files) {
  const root = { children: new Map() };
  for (const path of new Set(files)) {
    const parts = path.split("/");
    let parent = root;
    parts.forEach((name, i) => {
      const key = parts.slice(0, i + 1).join("/");
      if (!parent.children.has(name))
        parent.children.set(name, {
          name,
          path: key,
          folder: i < parts.length - 1,
          children: new Map(),
        });
      parent = parent.children.get(name);
    });
  }
  const sort = (node) =>
    [...node.children.values()]
      .sort(
        (a, b) =>
          Number(b.folder) - Number(a.folder) ||
          a.name.localeCompare(b.name, undefined, { numeric: true }),
      )
      .map((n) => ({ ...n, children: sort(n) }));
  return sort(root);
}
export function ancestorPaths(path) {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}
