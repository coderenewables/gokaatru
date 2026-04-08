export const algorithmHelp: Record<string, { label: string; description: string; recommended: string }> = {
  linear_least_squares: {
    label: "Linear Least Squares (Robust Huber)",
    description:
      "Iteratively reweighted least squares using Huber loss. Down-weights outlier residuals while preserving the linear relationship.",
    recommended: "General purpose. Good when the concurrent relationship is already strong.",
  },
  total_least_squares: {
    label: "Total Least Squares (Orthogonal)",
    description:
      "Fits a line by minimizing perpendicular distance, which accounts for uncertainty in both measured and reference datasets.",
    recommended: "Use when both the measured and reference series carry comparable noise.",
  },
  speedsort: {
    label: "SpeedSort",
    description:
      "Piecewise linear correction with a dog-leg low-speed segment and TLS on the higher-speed tail to reduce bias in calm conditions.",
    recommended: "Industry-standard default for bankable wind-resource correction studies.",
  },
  variance_ratio: {
    label: "Variance Ratio",
    description:
      "Distribution-matching method that rescales the reference series by matching measured and reference means and standard deviations.",
    recommended: "Use when preserving the corrected wind-speed distribution is more important than point prediction fit.",
  },
  xgboost: {
    label: "XGBoost (Machine Learning)",
    description:
      "Gradient-boosted trees with temporal, directional, and meteorological features to capture non-linear reference-to-site relationships.",
    recommended: "Use as a secondary diagnostic or when the deterministic models miss clear non-linear structure.",
  },
};