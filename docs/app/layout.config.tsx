import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";

export const baseOptions: BaseLayoutProps = {
  nav: {
    url: "/docs",
    title: (
      <span className="atm-docs-nav-title">
        <span className="atm-docs-nav-mark" aria-hidden="true" />
        <span className="atm-docs-nav-name">AITeachMe</span>
      </span>
    ),
  },
  themeSwitch: { enabled: false },
};
