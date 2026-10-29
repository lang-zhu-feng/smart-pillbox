import path from "node:path";
import { pathToFileURL } from "node:url";
import { PresentationFile } from "@oai/artifact-tool";

process.env.CODEX_PRIMARY_RUNTIME_NODE_MODULES = "C:/Users/liuzhanfei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules";

const SKILL_DIR = "C:/Users/liuzhanfei/.codex/plugins/cache/openai-primary-runtime/presentations/26.1009.11318/skills/presentations";
const workspaceDir = "C:/Users/liuzhanfei/Documents/ChatGPT/智慧药盒";
const candidatePath = path.join(workspaceDir, ".codex-finalizer", "智慧药盒_答辩高级动态版_candidate.pptx");
const finalPath = path.join(workspaceDir, "output", "智慧药盒_答辩高级动态加强版.pptx");
const stagingDir = path.join(workspaceDir, ".codex-finalizer");
const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR, "container_tools/artifact_tool_utils.mjs")).href);

const result = await finalizePresentation({
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable: "C:/Users/liuzhanfei/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
  integrityValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_package_integrity.py"),
  layoutValidatorPath: path.join(SKILL_DIR, "container_tools/inspect_presentation_layout_geometry.py"),
  layoutArgs: ["--expected-slide-size-emu", "12192000,6858000", "--validate-heading-fit"],
  fontPolicy: { basis: "design", families: ["Microsoft YaHei"] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir, "智慧药盒_答辩高级动态加强版.validation.json"),
});
console.log(JSON.stringify(result, null, 2));
