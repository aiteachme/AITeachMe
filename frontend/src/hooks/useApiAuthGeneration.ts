import { useEffect, useState } from "react";

import {
  API_AUTH_CHANGED_EVENT,
  getApiAuthGeneration,
} from "../api/client";

export function useApiAuthGeneration(): number {
  const [generation, setGeneration] = useState(getApiAuthGeneration);

  useEffect(() => {
    const handleAuthChange = () => {
      setGeneration(getApiAuthGeneration());
    };

    window.addEventListener(API_AUTH_CHANGED_EVENT, handleAuthChange);
    handleAuthChange();
    return () => window.removeEventListener(API_AUTH_CHANGED_EVENT, handleAuthChange);
  }, []);

  return generation;
}
