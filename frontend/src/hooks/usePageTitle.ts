import { useEffect } from "react";

const APP_NAME = "GoKaatru";

export function usePageTitle(pageTitle: string) {
  useEffect(() => {
    document.title = `${pageTitle} — ${APP_NAME}`;
    return () => {
      document.title = APP_NAME;
    };
  }, [pageTitle]);
}
