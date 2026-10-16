// Exercise real React components with the project's existing TypeScript compiler.
import { registerHooks } from "node:module";
import { existsSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const root = new URL("../../", import.meta.url);
registerHooks({
  resolve(specifier, context, next) {
    if (["next/link", "next/navigation"].includes(specifier))
      return next(specifier + ".js", context);
    const candidate = specifier.startsWith("@/")
      ? new URL(specifier.slice(2), root)
      : specifier.startsWith(".") && context.parentURL?.startsWith(root.href)
        ? new URL(specifier, context.parentURL)
        : null;
    if (candidate) {
      const path = fileURLToPath(candidate);
      for (const suffix of ["", ".tsx", ".ts", ".mjs"]) {
        if (existsSync(path + suffix) && statSync(path + suffix).isFile())
          return { url: pathToFileURL(path + suffix).href, shortCircuit: true };
      }
    }
    return next(specifier, context);
  },
  load(url, context, next) {
    if (url.startsWith(root.href) && /\.(tsx|ts)$/.test(url)) {
      const source = ts.transpileModule(readFileSync(new URL(url), "utf8"), {
        compilerOptions: {
          jsx: ts.JsxEmit.ReactJSX,
          module: ts.ModuleKind.ESNext,
          target: ts.ScriptTarget.ES2022,
        },
        fileName: fileURLToPath(url),
      }).outputText;
      return { format: "module", source, shortCircuit: true };
    }
    return next(url, context);
  },
});
