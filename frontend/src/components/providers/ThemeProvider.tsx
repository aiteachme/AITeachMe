import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
} from "react"

export type Theme = "dark" | "light" | "system"

export const THEME_STORAGE_KEY = "aiteachme-theme"

type ThemeProviderProps = {
  children: React.ReactNode
  defaultTheme?: Theme
  storageKey?: string
}

type ThemeProviderState = {
  theme: Theme
  setTheme: (theme: Theme) => void
}

const initialState: ThemeProviderState = {
  theme: "system",
  setTheme: () => null,
}

const ThemeProviderContext = createContext<ThemeProviderState>(initialState)

function isTheme(value: string | null): value is Theme {
  return value === "light" || value === "dark" || value === "system"
}

function resolveTheme(theme: Theme): "light" | "dark" {
  if (theme !== "system") {
    return theme
  }

  return window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light"
}

function applyTheme(theme: Theme) {
  const root = window.document.documentElement
  const resolvedTheme = resolveTheme(theme)

  root.classList.remove("light", "dark")
  root.classList.add(resolvedTheme)
  root.dataset.themePreference = theme
  root.style.colorScheme = resolvedTheme
}

function readStoredTheme(storageKey: string, fallbackTheme: Theme): Theme {
  try {
    const storedTheme = window.localStorage.getItem(storageKey)
    return isTheme(storedTheme) ? storedTheme : fallbackTheme
  } catch {
    return fallbackTheme
  }
}

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = THEME_STORAGE_KEY,
  ...props
}: ThemeProviderProps) {
  const [theme, setTheme] = useState<Theme>(
    () => readStoredTheme(storageKey, defaultTheme)
  )

  useLayoutEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    if (theme !== "system") {
      return
    }

    const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)")

    const handleChange = () => {
      applyTheme("system")
    }

    mediaQuery.addEventListener("change", handleChange)
    return () => mediaQuery.removeEventListener("change", handleChange)
  }, [theme])

  const value = useMemo<ThemeProviderState>(
    () => ({
      theme,
      setTheme: (nextTheme: Theme) => {
        try {
          window.localStorage.setItem(storageKey, nextTheme)
        } catch {
          // Ignore storage failures and still apply the theme in memory.
        }
        setTheme(nextTheme)
      },
    }),
    [storageKey, theme],
  )

  return (
    <ThemeProviderContext.Provider {...props} value={value}>
      {children}
    </ThemeProviderContext.Provider>
  )
}

export const useTheme = () => {
  const context = useContext(ThemeProviderContext)

  if (context === undefined)
    throw new Error("useTheme must be used within a ThemeProvider")

  return context
}
