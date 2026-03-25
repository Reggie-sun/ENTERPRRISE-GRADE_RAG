import { Card, HeroCard, StatusPill } from '@/components';

export function SopPage() {
  return (
    <div className="grid gap-5">
      <HeroCard>
        <div className="inline-flex items-center gap-2 mb-4 px-3 py-1.5 rounded-full bg-[rgba(182,70,47,0.09)] text-accent-deep text-sm font-bold uppercase tracking-wider">
          SOP Center
        </div>
        <h2 className="m-0 font-serif text-3xl md:text-4xl leading-tight tracking-tight text-ink">
          SOP 页面先预留独立入口，后面再接分类、预览和下载能力。
        </h2>
        <p className="m-0 mt-3 max-w-[62ch] leading-relaxed text-ink-soft">
          这页是给企业用户查标准文档用的，不应该继续和上传、检索、问答混在一起。先把路由和壳子分出来，后面上 SOP 能力时就不会再牵一发而动全身。
        </p>
      </HeroCard>

      <section className="grid grid-cols-12 gap-5">
        <Card className="col-span-7 max-md:col-span-12">
          <h3 className="m-0 text-xl font-semibold text-ink">预留能力</h3>
          <div className="mt-4 grid gap-3 text-sm text-ink-soft">
            <p className="m-0">1. 按部门、工序、场景分类展示 SOP 文档。</p>
            <p className="m-0">2. 支持在线预览 SOP 内容，并保留下载入口。</p>
            <p className="m-0">3. 后续可和文档主数据、权限体系联动，而不是另起一套数据结构。</p>
          </div>
        </Card>

        <Card className="col-span-5 max-md:col-span-12 bg-panel border-[rgba(182,70,47,0.1)]">
          <h3 className="m-0 text-xl font-semibold text-ink">当前状态</h3>
          <div className="mt-4">
            <StatusPill tone="warn">页面已预留，业务尚未落地</StatusPill>
          </div>
          <p className="m-0 mt-4 text-sm leading-relaxed text-ink-soft">
            后面做 v0.4/v0.5 时，可以直接在这页接列表、预览、Word/PDF 下载，不需要再从单页 demo 里拆一次。
          </p>
        </Card>
      </section>
    </div>
  );
}
