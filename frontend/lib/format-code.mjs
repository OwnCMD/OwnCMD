import { format } from "prettier/standalone";
import * as babel from "prettier/plugins/babel";
import * as estree from "prettier/plugins/estree";
import * as typescript from "prettier/plugins/typescript";
import * as html from "prettier/plugins/html";
import * as postcss from "prettier/plugins/postcss";
import * as markdown from "prettier/plugins/markdown";
import * as yaml from "prettier/plugins/yaml";
export const parsers = {
  js: "babel",
  jsx: "babel",
  mjs: "babel",
  cjs: "babel",
  ts: "typescript",
  tsx: "typescript",
  json: "json",
  html: "html",
  htm: "html",
  vue: "vue",
  css: "css",
  scss: "scss",
  less: "less",
  md: "markdown",
  markdown: "markdown",
  yml: "yaml",
  yaml: "yaml",
};
export function parserFor(path) {
  return parsers[path.split(".").at(-1).toLowerCase()];
}
export async function formatCode(path, source) {
  const parser = parserFor(path);
  if (!parser)
    throw new Error("Formatting is not available for this file type.");
  if (source.length > 512 * 1024)
    throw new Error("This file is too large for automatic formatting.");
  return format(source, {
    parser,
    plugins: [babel, estree, typescript, html, postcss, markdown, yaml],
    tabWidth: 2,
    printWidth: 90,
    endOfLine: "auto",
  });
}
