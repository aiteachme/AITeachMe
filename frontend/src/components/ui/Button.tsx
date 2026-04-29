import * as React from "react";
import { cn } from "../../lib/utils";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "ghost" | "outline";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    return (
      <button
        className={cn(
          "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-white dark:focus-visible:ring-offset-slate-950 disabled:pointer-events-none disabled:opacity-50",
          {
            "bg-slate-900 text-white shadow hover:bg-slate-800 hover:shadow-md dark:bg-slate-100 dark:text-slate-900 dark:hover:bg-white": variant === "default",
            "text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800/70": variant === "ghost",
            "border border-slate-200/80 bg-white text-slate-700 hover:bg-slate-50 shadow-sm dark:border-slate-700/80 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800": variant === "outline",
          },
          {
            "h-11 px-4 py-2 sm:h-10": size === "default",
            "h-10 px-3 sm:h-9": size === "sm",
            "h-12 px-8 sm:h-11": size === "lg",
            "h-11 w-11 sm:h-10 sm:w-10": size === "icon",
          },
          className
        )}
        ref={ref}
        {...props}
      />
    );
  }
);

Button.displayName = "Button";

export { Button };
