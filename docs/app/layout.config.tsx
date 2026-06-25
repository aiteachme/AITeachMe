import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";

export const baseOptions: BaseLayoutProps = {
  nav: {
    title: (
      <span className="atm-docs-nav-title">
        <span className="atm-docs-nav-mark" aria-hidden="true">
          ATM
        </span>
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
