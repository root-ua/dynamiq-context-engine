import Link from "next/link";

export function Footer({ className }: { className?: string }) {
  return (
    <footer
      className={
        "flex flex-wrap items-center justify-between gap-3 border-t px-4 py-4 text-xs text-muted-foreground md:px-6 " +
        (className ?? "")
      }
    >
      <div>© {new Date().getFullYear()} Dynamiq</div>
      <nav className="flex flex-wrap gap-4">
        <Link className="hover:text-foreground" href="/legal/terms">
          Terms
        </Link>
        <Link className="hover:text-foreground" href="/legal/privacy">
          Privacy
        </Link>
        <Link className="hover:text-foreground" href="/contact">
          Contact
        </Link>
        <a
          className="hover:text-foreground"
          href="https://status.render.com"
          target="_blank"
          rel="noopener noreferrer"
        >
          Status ↗
        </a>
      </nav>
    </footer>
  );
}
