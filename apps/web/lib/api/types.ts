// Public aliases derive from FastAPI OpenAPI; do not duplicate response shapes here.
import type { components } from "@/lib/generated/api";

export type MemoryType = components["schemas"]["MemoryType"];
export type MemoryStatus = components["schemas"]["MemoryStatus"];
export type MemoryRelation = components["schemas"]["MemoryRelation"];
export type ExecutionMode = components["schemas"]["ExecutionMode"];
export type InteractionStatus = components["schemas"]["InteractionStatus"];
export type IngestDecisionType = components["schemas"]["IngestDecisionType"];
export type MemoryEventType = components["schemas"]["MemoryEventType"];
export type MemoryRecord = components["schemas"]["MemoryRecord"];
export type MemoryEvent = components["schemas"]["MemoryEvent"];
export type MemoryVersion = components["schemas"]["MemoryVersion"];
export type MemoryListResponse = components["schemas"]["MemoryListResponse"];
export type MemoryHistoryResponse =
  components["schemas"]["MemoryHistoryResponse"];
export type MemoryTypeCount = components["schemas"]["MemoryTypeCount"];
export type OverviewResponse = components["schemas"]["OverviewResponse"];
export type DemoScenario = components["schemas"]["DemoScenario"];
export type DemoQuery = components["schemas"]["DemoQuery"];
export type DemoCatalogResponse = components["schemas"]["DemoCatalogResponse"];
export type CandidateMemory = components["schemas"]["CandidateMemory"];
export type IngestDecision = components["schemas"]["IngestDecision"];
export type TraceStep = components["schemas"]["TraceStep"];
export type InteractionTrace = components["schemas"]["InteractionTrace"];
export type IngestInteractionResponse =
  components["schemas"]["IngestInteractionResponse"];
export type RecallScoreBreakdown =
  components["schemas"]["RecallScoreBreakdown"];
export type RecallItem = components["schemas"]["RecallItem"];
export type RecallComparisonItem =
  components["schemas"]["RecallComparisonItem"];
export type RecallComparisonResponse =
  components["schemas"]["RecallComparisonResponse"];
export type ForgetMemoryResponse =
  components["schemas"]["ForgetMemoryResponse"];
export type ResolveMemoryResponse =
  components["schemas"]["ResolveMemoryResponse"];
export type CapabilitiesResponse =
  components["schemas"]["CapabilitiesResponse"];
export type ReviewAction = components["schemas"]["ResolveReviewRequest"]["action"];
export type ReviewStatus = "pending" | "resolved";
export type ReviewItem = components["schemas"]["ReviewItem"];
export type ReviewListResponse = components["schemas"]["ReviewListResponse"];
