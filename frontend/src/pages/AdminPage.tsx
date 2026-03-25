import { Card, HeroCard, StatusPill } from '@/components';

export function AdminPage() {
  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
          Admin
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          管理后台也需要独立页面，不然登录和权限只会把 demo 页越堆越乱。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          现在先把后台页占出来，后面身份目录、角色权限、租户配置和系统参数都能按模块往这里收，不会再混进业务验证页。
        </p>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-md:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">后续承接内容</h3>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <p className="m-0">1. 登录与 token 校验。</p>
            <p className="m-0">2. 部门、角色、用户目录与权限映射。</p>
            <p className="m-0">3. 租户配置、模型开关、系统级运行状态。</p>
          </div>
        </Card>

        <Card className="col-span-5 max-md:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前状态</h3>
          <div className="mt-4">
            <StatusPill tone="warn">页面已预留，等待 v0.3 鉴权接入</StatusPill>
          </div>
          <p className="m-0 mt-4 text-sm leading-relaxed text-ink-soft">
            后端身份目录底座已经起了，这页后续可以直接接登录、用户详情和权限配置入口。
          </p>
        </Card>
      </section>
    </div>
  );
}
