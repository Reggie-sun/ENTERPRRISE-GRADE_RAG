import { getDepartmentScopeSummary, getRoleExperience, useAuth } from '@/auth';
import { Card, HeroCard, StatusPill } from '@/components';

export function AdminPage() {
  const { profile } = useAuth();
  const experience = getRoleExperience(profile);
  const scopeSummary = getDepartmentScopeSummary(profile);

  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
          Admin
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          管理后台只对系统管理员开放，用来承接全局身份、权限和配置入口。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          {experience.workspaceBoundary}
          这里不会再混入普通业务页，而是专门留给系统级治理动作。
        </p>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-md:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">后续承接内容</h3>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <p className="m-0">1. 用户、部门、角色目录与权限映射。</p>
            <p className="m-0">2. 模型、检索参数和系统配置入口。</p>
            <p className="m-0">3. 日志、审计和后续系统级运行状态。</p>
          </div>
        </Card>

        <Card className="col-span-5 max-md:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前状态</h3>
          <div className="mt-4">
            <StatusPill tone="warn">已完成入口级鉴权，业务模块待继续落地</StatusPill>
          </div>
          <p className="m-0 mt-4 text-sm leading-relaxed text-ink-soft">
            {scopeSummary}
          </p>
          <p className="m-0 mt-3 text-sm leading-relaxed text-ink-soft">
            这一页现在先承接系统管理员视图，后面继续按 v0.4 之后的计划往里补配置和治理模块。
          </p>
        </Card>
      </section>
    </div>
  );
}
