// Keep code-server's /proxy/<port>/ prefix as well as direct host:port URLs.
const pathname = window.location.pathname.replace(/\/(?:admin|login)(?:\/.*)?$/, "/");
export const basePath = pathname.endsWith("/") ? pathname : `${pathname}/`;
export const isAdminPath = /\/admin(?:\/|$)/.test(window.location.pathname);
export const appUrl = (path = "") => new URL(path, new URL(basePath, window.location.origin)).href;
