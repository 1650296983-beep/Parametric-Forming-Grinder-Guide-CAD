export type Shape = "tile" | "bread";
export type PreformShape = "block" | "same_r_tile";

export interface Machine {
  id: string;
  name: string;
  guide_type: "single_guide" | "double_guide";
  guide_length: number;
  guide_sections: number;
  wheel_positions: string[];
  section_outer_width: number;
  section_center_opening: number;
  section_slot_base_height: number;
  template_coordinate_system: string;
  supported_by_web_generation: boolean;
  wheel_radius: number;
}

export interface DesignInput {
  machine_type: string;
  guide_rail_type: string;
  wheel_sequence: string[];
  first_wheel_side: string;
  template_coordinate_system: string;
  finished_spec: string;
  pre_grinding_spec: string;
  product_shape_after: "tile_shape" | "bread_shape";
  product_shape_before: "rectangular_block" | "same_r_tile";
  /**
   * Compatibility-only metadata. The Web form intentionally does not send it:
   * the tolerances embedded in pre_grinding_spec are the single source of truth.
   */
  tolerance?: Record<string, number | null>;
  relief: string;
  single_side_or_high_requirement: boolean;
  high_symmetry_requirement: boolean;
  large_tile_clearance: boolean;
  wheel_radius: number;
}

export interface ValidationResult {
  machine: Machine;
  decision: {
    groove_profile: string;
    final_section_profile_type: string;
    guide_profile_source: string;
    R_form_source: string;
    arc_radius: number | null;
    arc_side: string | null;
    flat_side: string | null;
    warnings: string[];
    process_options: {
      single_side_or_high_requirement: boolean;
      high_symmetry_requirement: boolean;
      large_tile_clearance: boolean;
      wheel_radius: number;
    };
  };
  derived: {
    slot_width: number;
    slot_width_tolerance: number;
    slot_width_raw: number;
    guide_thickness: number;
    thickness_clearance_mid: number;
    center_opening: number;
    relief_label: string;
    outer_width: number;
    outer_height: number;
  };
  message: string;
}

export interface GeneratedFile {
  label: string;
  name: string;
  url: string;
}

export interface UserSession {
  username: string;
  role: "administrator";
}

export interface EngineStatus {
  running: boolean;
  apiBaseUrl: string | null;
  error: string | null;
}

export interface AutoCadInstallation {
  path: string;
  version: string | null;
  source: string;
}

export interface DesktopSettings {
  autocad_core_console: string | null;
  app_data_root: string;
  autocad: {
    available: boolean;
    path: string | null;
    version: string | null;
    source: string | null;
    detected: AutoCadInstallation[];
  };
}

export interface GenerationResult {
  task_id: string;
  ok: boolean;
  stderr: string;
  release_allowed?: boolean;
  preview?: GeneratedFile | null;
  files?: Record<string, GeneratedFile>;
}

export type TaskStatus = "running" | "passed" | "failed";

export interface TaskDerivedSummary {
  slot_width: number | null;
  guide_thickness: number | null;
  groove_profile: string | null;
}

export interface TaskSummary {
  task_id: string;
  task_name: string;
  created_at: string;
  updated_at: string;
  created_by: string | null;
  can_delete: boolean;
  status: TaskStatus;
  error: string | null;
  machine_id: string;
  machine_name: string;
  finished_spec: string;
  pre_grinding_spec: string;
  finished_shape: DesignInput["product_shape_after"];
  pre_grinding_shape: DesignInput["product_shape_before"];
  release_allowed: boolean;
  derived: TaskDerivedSummary;
  preview?: GeneratedFile | null;
  files: Record<string, GeneratedFile>;
}

export interface BulkDeleteResult {
  deleted: string[];
  skipped: Array<{ task_id: string; reason: string }>;
}

export interface TaskMetrics {
  total: number;
  today: number;
  passed: number;
  failed: number;
  running: number;
}

export interface TaskHistoryResult {
  items: TaskSummary[];
  metrics: TaskMetrics;
  retention_days: number;
}

export interface TaskDetail extends TaskSummary {
  input: DesignInput;
  audit: {
    release_allowed: boolean;
    inspection_passed: boolean;
    dimension_points_passed: boolean;
    workflow: string[];
  };
}
