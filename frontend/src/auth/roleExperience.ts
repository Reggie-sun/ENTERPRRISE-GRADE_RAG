import type { AuthProfileResponse, UserRole } from '@/api';

export interface RoleExperience {
  roleLabel: string;
  portalTitle: string;
  portalDescription: string;
  portalHeaderNote: string;
  homeFocusTitle: string;
  homeFocusPoints: string[];
  suggestedQuestions: string[];
  myCapabilityItems: string[];
  libraryScopeDescription: string;
  sopScopeDescription: string;
  workspaceTitle: string;
  workspaceDescription: string;
  workspaceBoundary: string;
  workspaceEntryLabel: string;
}

function resolveRoleLabel(roleId: UserRole | null | undefined): string {
  switch (roleId) {
    case 'department_admin':
      return '部门管理员';
    case 'sys_admin':
      return '系统管理员';
    case 'employee':
    default:
      return '普通员工';
  }
}

export function getDepartmentScopeSummary(profile: AuthProfileResponse | null | undefined): string {
  if (!profile) {
    return '待登录后确定部门范围。';
  }

  const departmentName = profile.department.department_name;
  const departmentCount = profile.accessible_department_ids.length;

  if (profile.user.role_id === 'sys_admin') {
    return `当前可跨部门查看资料，主部门为 ${departmentName}，已授权 ${departmentCount} 个部门。`;
  }

  return `当前仅在 ${departmentName} 范围内查看和使用已授权内容。`;
}

export function getRoleExperience(profile: AuthProfileResponse | null | undefined): RoleExperience {
  const roleId = profile?.user.role_id || 'employee';
  const roleLabel = resolveRoleLabel(roleId);
  const departmentName = profile?.department.department_name || '当前部门';

  switch (roleId) {
    case 'department_admin':
      return {
        roleLabel,
        portalTitle: `先服务 ${departmentName} 团队，再处理本部门知识维护。`,
        portalDescription:
          '门户聚焦日常知识服务，管理中心承接本部门资料维护、服务质量检查和标准流程管理，让业务入口与管理入口各自清晰。',
        portalHeaderNote:
          '你当前既可以在门户里直接生成和查看 SOP，也可以进入管理中心维护本部门知识资产。',
        homeFocusTitle: '当前更适合从这三类动作开始',
        homeFocusPoints: [
          '快速回答本部门同事常见问题，减少重复解释。',
          '查看最近更新的 SOP 和资料，判断是否需要补充或重建。',
          '必要时进入管理中心处理本部门资料、知识检索和服务效果检查。',
        ],
        suggestedQuestions: [
          '本部门最近更新了哪些 SOP 或处理资料？',
          `${departmentName}遇到系统、流程或设备异常时，标准处理流程是什么？`,
          '新同事入岗前应该优先阅读哪些资料？',
        ],
        myCapabilityItems: [
          '查看并使用本部门已授权的知识资料和 SOP。',
          '进入管理中心维护本部门资料、问答效果和标准流程。',
          '不能跨部门管理其他团队的资料与配置。',
        ],
        libraryScopeDescription:
          '资料中心会优先展示你所在部门可访问的资料，适合先确认最近更新和常用内容。',
        sopScopeDescription:
          'SOP 中心既能基于当前文档直接生成草稿，也会聚合本部门可见的标准流程，适合一边生成一边查标准操作说明。',
        workspaceTitle: '本部门管理中心',
        workspaceDescription:
          '这里集中展示资料上传、知识服务检查和流程维护能力，管理边界严格限制在本部门内。',
        workspaceBoundary: `你当前只能维护 ${departmentName} 的文档和知识结果。`,
        workspaceEntryLabel: '进入部门管理中心',
      };
    case 'sys_admin':
      return {
        roleLabel,
        portalTitle: '同时掌握全局知识入口和系统治理入口。',
        portalDescription:
          '平台管理员可在门户中处理跨部门知识服务，也可在管理中心中统一处理资料治理、权限配置和平台运行事务。',
        portalHeaderNote:
          '你当前拥有全局视角，既可以按业务入口直接生成和查看 SOP，也可以进入平台级管理中心。',
        homeFocusTitle: '当前更适合从这三类动作开始',
        homeFocusPoints: [
          '跨部门查看知识资料和 SOP，确认各团队的内容覆盖情况。',
          '通过问答与资料浏览判断知识库是否存在缺口。',
          '进入管理中心和后台入口处理全局配置、权限与平台服务问题。',
        ],
        suggestedQuestions: [
          '不同部门最近更新了哪些关键知识资料？',
          '当前知识库里哪些 SOP 最适合作为统一标准入口？',
          '跨部门常见问题有哪些可以沉淀成统一回答？',
        ],
        myCapabilityItems: [
          '查看全部已授权部门的资料、SOP 和问答结果。',
          '进入管理中心处理全局资料治理、平台状态和服务配置。',
          '进入管理后台处理身份、权限和系统配置模块。',
        ],
        libraryScopeDescription:
          '资料中心可作为全局浏览入口，适合跨部门抽查资料覆盖、更新时间和预览内容。',
        sopScopeDescription:
          'SOP 中心当前既可按文档直接生成草稿，也可按部门和分类浏览全局标准流程。',
        workspaceTitle: '平台管理中心',
        workspaceDescription:
          '这里集中承接资料维护、跨部门服务检查、权限管理和平台运行入口。',
        workspaceBoundary: '你当前拥有全局管理范围，建议先按部门和分类逐步处理。',
        workspaceEntryLabel: '进入平台管理中心',
      };
    case 'employee':
    default:
      return {
        roleLabel,
        portalTitle: `先在 ${departmentName} 范围内提问、查 SOP、看资料。`,
        portalDescription:
          '门户只保留日常工作真正需要的功能，让你更快找到答案、查看资料并使用标准流程服务。',
        portalHeaderNote:
          '你当前使用的是员工视角，系统会自动按部门过滤资料、问答结果和 SOP 内容，并支持直接基于文档生成流程草稿。',
        homeFocusTitle: '当前更适合从这三类动作开始',
        homeFocusPoints: [
          '直接提问，快速获取带来源依据的回答。',
          '去 SOP 中心直接上传文档生成草稿，或按部门和场景找到标准流程。',
          '在知识库里预览和下载你当前部门已授权的资料。',
        ],
        suggestedQuestions: [
          '设备报警后第一步应该检查什么？',
          '本部门标准开机 SOP 的核心步骤是什么？',
          '新员工上岗前需要阅读哪些资料？',
        ],
        myCapabilityItems: [
          '智能问答、SOP 生成、SOP 查看和知识资料浏览。',
          '系统会自动限制到你当前部门的已授权内容。',
          '不会看到管理中心、全局配置和跨部门管理入口。',
        ],
        libraryScopeDescription:
          '资料中心只展示你当前部门已授权的资料，适合先通过标题、分类和预览确认是否需要下载。',
        sopScopeDescription:
          'SOP 中心优先用于直接生成或查找标准流程，不需要先理解后台处理过程。',
        workspaceTitle: '平台管理中心',
        workspaceDescription:
          '普通员工无需进入管理中心；资料治理、权限配置和平台维护由管理员统一处理。',
        workspaceBoundary: '当前角色没有管理入口，仅保留知识服务使用能力。',
        workspaceEntryLabel: '进入管理中心',
      };
  }
}
