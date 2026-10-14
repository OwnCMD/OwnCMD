import { formatCode } from "./format-code.mjs";
self.onmessage = async ({ data }) => {
  try {
    self.postMessage({ value: await formatCode(data.path, data.source) });
  } catch (error) {
    self.postMessage({ error: String(error.message).split("\n")[0] });
  }
};
