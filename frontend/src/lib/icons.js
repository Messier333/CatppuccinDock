export const icons = Object.fromEntries(Object.entries(import.meta.glob("../assets/link-icons/*.svg", { eager: true, query: "?raw", import: "default" }))
  .map(([path, svg]) => [path.split("/").pop().replace(".svg", ""), svg]));
