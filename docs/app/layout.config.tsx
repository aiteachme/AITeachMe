import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";

export const baseOptions: BaseLayoutProps = {
  nav: {
    url: "/docs",
    title: (
      <span className="atm-docs-nav-title">
        <img className="atm-docs-nav-logo" src="/logo.svg" alt="" />
        <span>AITeachMe</span>
      </span>
    ),
  },
  links: [
    {
      text: "GitHub",
      url: "https://github.com/aiteachme/AITeachMe",
      external: true,
    },
  ],
};
