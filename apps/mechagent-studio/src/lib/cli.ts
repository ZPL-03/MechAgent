export function reproducibleCliCommand(
  requestText: string,
  useLlmAgents: boolean,
  pythonExecutable: string | undefined
) {
  const requestValue = requestText.trim();
  const parts = [
    pythonLauncher(pythonExecutable),
    "-m",
    "mechagent.cli",
    "run",
    powerShellQuote(requestValue),
    "--config",
    "config/mechagent.yaml"
  ];
  if (useLlmAgents) {
    parts.push("--llm-agents");
  }
  return parts.join(" ");
}

function pythonLauncher(pythonExecutable: string | undefined) {
  const executable = pythonExecutable?.trim() || "python";
  if (executable === "python") {
    return "python";
  }
  return `& ${powerShellQuote(executable)}`;
}

function powerShellQuote(value: string) {
  return `"${value.replace(/`/g, "``").replace(/\$/g, "`$").replace(/"/g, '`"')}"`;
}
