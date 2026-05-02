export {};

type ElectronEditCommand = "undo" | "redo" | "cut" | "copy" | "paste" | "delete" | "selectAll";
type ElectronNavigationState = {
  canGoBack: boolean;
  canGoForward: boolean;
};

declare global {
  interface Window {
    aiteachmeDesktop?: {
      apiBaseUrl: string;
      desktopFlavor?: "local" | "remote";
    };
    electronWindow?: {
      minimize: () => Promise<void>;
      toggleMaximize: () => Promise<boolean>;
      close: () => Promise<void>;
      isMaximized: () => Promise<boolean>;
      reload: () => Promise<void>;
      goBack: () => Promise<boolean>;
      goForward: () => Promise<boolean>;
      canGoBack: () => Promise<boolean>;
      canGoForward: () => Promise<boolean>;
      toggleDevTools: () => Promise<void>;
      openExternal: (url: string) => Promise<boolean>;
      runEditCommand: (command: ElectronEditCommand) => Promise<boolean>;
      onMaximizedChange: (callback: (isMaximized: boolean) => void) => () => void;
      onNavigationStateChange: (callback: (state: ElectronNavigationState) => void) => () => void;
    };
  }
}
