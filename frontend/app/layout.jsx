import "@fontsource-variable/inter";
import "@xterm/xterm/css/xterm.css";
import "./globals.css";
import "./workspace-refinements.css";
import "./operations.css";
import "./admin-refinements.css";
import "./integrations.css";
export const metadata = {
  title: "OwnCMD — Your AI workspace",
  icons: { icon: "/static/owncmd.svg" },
  description:
    "A focused workspace for conversations, research, and getting work done.",
};
export default function Layout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
