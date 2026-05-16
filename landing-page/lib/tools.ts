export const TOOLS = [
  "doctor",
  "voices",
  "list_projects",
  "project_status",
  "init",
  "import_source",
  "read_state",
  "write_state",
  "tts",
  "transcribe",
  "silence",
  "cut",
  "compose",
  "export",
  "schema",
  "add_vo_segment",
  "add_slide",
  "set_compose_output",
  "preview_slide",
  "is_up_to_date",
] as const;

export type ToolName = (typeof TOOLS)[number];
