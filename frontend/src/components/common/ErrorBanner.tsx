import { ApiError } from "../../lib/api";

type ErrorBannerProps = {
  error: unknown;
  title?: string;
};

function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    return typeof error.detail === "string" ? error.detail : error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string") {
    return error;
  }
  return "The last request failed.";
}

export function ErrorBanner({ error, title = "Request failed" }: ErrorBannerProps) {
  return (
    <div className="error-banner" role="alert">
      <strong>{title}</strong>
      <p>{errorMessage(error)}</p>
    </div>
  );
}