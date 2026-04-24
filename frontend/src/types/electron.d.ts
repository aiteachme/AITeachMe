export {};

type ElectronEditCommand = "undo" | "redo" | "cut" | "copy" | "paste" | "delete" | "selectAll";

declare global {
  interface Window {
    aiteachmeDesktop?: {
      apiBaseUrl: string;
    };
    electronWindow?: {
      minimize: () => Promise<void>;
      toggleMaximize: () => Promise<boolean>;
      close: () => Promise<void>;
      isMaximized: () => Promise<boolean>;
      reload: () => Promise<void>;
      toggleDevTools: () => Promise<void>;
      openExternal: (url: string) => Promise<boolean>;
      runEditCommand: (command: ElectronEditCommand) => Promise<boolean>;
      onMaximizedChange: (callback: (isMaximized: boolean) => void) => () => void;
    };
  }
}
