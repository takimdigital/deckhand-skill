// Deckhand guard for OpenCode — written by `dh harness install --harness opencode`; removed by `dh harness uninstall`.
// It calls the same `dh hook` every other harness uses: one policy, data-driven (skill data/harness.json).
// Outside a deckhand project the hook answers nothing; only a guard decision (exit 2) blocks a tool call.
import { spawnSync } from "node:child_process";

const DH = __DH__;

function hook(event, payload) {
  return spawnSync(`${DH} hook ${event} --harness __HARNESS__`, {
    shell: true, input: JSON.stringify(payload), encoding: "utf8", timeout: 30000,
  });
}

export const Deckhand = async ({ directory }) => ({
  "tool.execute.before": async (input, output) => {
    const r = hook("pre", { tool_name: input.tool, tool_input: output.args ?? {}, cwd: directory });
    if (r.status === 2) throw new Error((r.stderr || "").trim() || "Blocked by Deckhand");
  },
  "tool.execute.after": async (input, output) => {
    hook("post", { tool_name: input.tool, tool_input: input.args ?? output?.args ?? {}, tool_response: output ?? {}, cwd: directory });
  },
});
