import type { OpsRerankCanarySummary } from '@/api';

type DecisionTone = 'ok' | 'warn' | 'error' | 'default';

export type RerankCanaryDecisionCode =
  | 'eligible'
  | 'hold'
  | 'provider_active'
  | 'rollback_active'
  | 'not_applicable';

export type RerankCanaryDecisionFilter = 'all' | RerankCanaryDecisionCode;

export interface RerankDecisionPresentation {
  label: string;
  title: string;
  summary: string;
  recommendedAction: string;
  tone: DecisionTone;
  pageActionLabel: string | null;
  pageActionPath: string | null;
}

export const PRIMARY_RERANK_CANARY_DECISIONS: RerankCanaryDecisionCode[] = [
  'eligible',
  'hold',
  'provider_active',
  'rollback_active',
];

export const RERANK_CANARY_DECISION_FILTERS: Array<{
  value: RerankCanaryDecisionFilter;
  label: string;
}> = [
  { value: 'all', label: '全部样本' },
  { value: 'eligible', label: 'eligible / 可推进' },
  { value: 'hold', label: 'hold / 继续观察' },
  { value: 'provider_active', label: 'provider_active / 已在 provider' },
  { value: 'rollback_active', label: 'rollback_active / 回退生效中' },
  { value: 'not_applicable', label: 'not_applicable / 不适用' },
];

export function getRerankDecisionPresentation(
  decision: string | null | undefined,
  options?: {
    canAccessAdmin?: boolean;
  },
): RerankDecisionPresentation {
  const canAccessAdmin = options?.canAccessAdmin ?? false;
  switch (decision) {
    case 'eligible':
      return {
        label: '可推进',
        title: 'provider 候选已经值得推进',
        summary: '这条样本里 provider 候选可用，且和 heuristic 基线出现了可观察差异。',
        recommendedAction: canAccessAdmin
          ? '先在检索页复核这条 query 的排序差异；确认无误后，把 default_strategy 切到 provider 做真实流量验证。'
          : '先在检索页复核这条 query 的排序差异；确认无误后，请系统管理员把 default_strategy 切到 provider 做真实流量验证。',
        tone: 'ok',
        pageActionLabel: '去检索页复核样本',
        pageActionPath: '/workspace/retrieval',
      };
    case 'hold':
      return {
        label: '继续观察',
        title: '当前样本还不值得切默认策略',
        summary: 'provider 候选暂时不可用，或当前样本和 heuristic 基线几乎一致。',
        recommendedAction: '继续保持 heuristic 默认，换更有代表性的 query 再做 canary，对比能否稳定产生排序差异。',
        tone: 'warn',
        pageActionLabel: '去检索页补样本',
        pageActionPath: '/workspace/retrieval',
      };
    case 'provider_active':
      return {
        label: '已在 provider',
        title: 'provider 已经是默认主路径',
        summary: '当前默认策略已经真实走 provider，这条样本不是“要不要切默认”的问题，而是“是否继续保持”的问题。',
        recommendedAction: '继续保持 provider 默认，重点观察真实流量下的失败率、锁定情况和排序稳定性，不需要再次切换。',
        tone: 'ok',
        pageActionLabel: '去检索页抽查结果',
        pageActionPath: '/workspace/retrieval',
      };
    case 'rollback_active':
      return {
        label: '回退生效中',
        title: 'provider 默认配置和实际生效路径已经不一致',
        summary: '当前默认仍写着 provider，但样本生成时实际已退回 heuristic，说明 provider 健康或锁定状态存在问题。',
        recommendedAction: canAccessAdmin
          ? '先把 default_strategy 回滚到 heuristic，避免页面配置与真实流量状态继续分叉；然后再排查 provider 健康与锁定来源。'
          : '联系系统管理员把 default_strategy 回滚到 heuristic，并优先排查 provider 健康与锁定来源。',
        tone: 'error',
        pageActionLabel: canAccessAdmin ? '去管理页处理回滚' : '去检索页查看异常样本',
        pageActionPath: canAccessAdmin ? '/workspace/admin' : '/workspace/retrieval',
      };
    case 'not_applicable':
      return {
        label: '不适用',
        title: '当前没有可提升的 provider 路径',
        summary: '系统当前没有配置模型级 rerank provider，这批样本不参与切换判读。',
        recommendedAction: '继续保持 heuristic 默认。如果后续要评估 provider，再先补充模型级 rerank 配置。',
        tone: 'default',
        pageActionLabel: canAccessAdmin ? '去管理页查看配置' : null,
        pageActionPath: canAccessAdmin ? '/workspace/admin' : null,
      };
    default:
      return {
        label: '待判读',
        title: '样本还没有稳定落到已知结论',
        summary: '当前样本没有命中既定判读桶，先回到检索页复核 query、候选量和 provider 健康状态。',
        recommendedAction: '优先查看最新 compare 结果和 provider 健康状态，再决定是否需要补样本或调整默认策略。',
        tone: 'default',
        pageActionLabel: '去检索页查看样本',
        pageActionPath: '/workspace/retrieval',
      };
  }
}

export function getRerankCanaryDecisionCount(
  summary: OpsRerankCanarySummary | null | undefined,
  decision: RerankCanaryDecisionCode,
): number {
  if (!summary) {
    return 0;
  }
  switch (decision) {
    case 'eligible':
      return summary.eligible_count;
    case 'hold':
      return summary.hold_count;
    case 'provider_active':
      return summary.provider_active_count;
    case 'rollback_active':
      return summary.rollback_active_count;
    case 'not_applicable':
      return summary.not_applicable_count;
    default:
      return 0;
  }
}
