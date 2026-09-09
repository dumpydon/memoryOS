import nextConfig from "eslint-config-next/core-web-vitals";

// eslint-config-next v16 exports a native flat-config array. Using it directly
// avoids translating a flat config through FlatCompat (which creates circular
// plugin objects under ESLint 9).
export default nextConfig;
