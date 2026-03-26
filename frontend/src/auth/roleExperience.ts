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
          '门户先给你业务入口，工作台再承接本部门资料维护、验证和排障，避免把管理员日常工作和普通员工视角混在一起。',
        portalHeaderNote:
          '你当前既可以使用门户里的问答和 SOP，也可以进入工作台维护本部门知识资产。',
        homeFocusTitle: '当前更适合从这三类动作开始',
        homeFocusPoints: [
          '快速回答本部门同事常见问题，减少重复解释。',
          '查看最近更新的 SOP 和资料，判断是否需要补充或重建。',
          '必要时进入工作台处理本部门文档、检索和问答验证。',
        ],
        suggestedQuestions: [
          '本部门最近更新了哪些 SOP 或处理资料？',
          `${departmentName}遇到系统、流程或设备异常时，标准处理流程是什么？`,
          '新同事入岗前应该优先阅读哪些资料？',
        ],
        myCapabilityItems: [
          '查看并使用本部门已授权的知识资料和 SOP。',
          '进入工作台维护本部门文档、检索和问答效果。',
          '不能跨部门管理其他团队的资料和配置。',
        ],
        libraryScopeDescription:
          '资料中心会优先展示你所在部门可访问的资料，适合先确认最近更新和常用内容。',
        sopScopeDescription:
          'SOP 中心会聚合本部门可见的标准流程，适合直接定位标准操作说明。',
        workspaceTitle: '本部门工作台',
        workspaceDescription:
          '工作台保留上传、检索、问答和排障信息，但管理边界严格限制在本部门内。',
        workspaceBoundary: `你当前只能维护 ${departmentName} 的文档和知识结果。`,
        workspaceEntryLabel: '进入部门工作台',
      };
    case 'sys_admin':
      return {
        roleLabel,
        portalTitle: '同时掌握全局知识入口和系统治理入口。',
        portalDescription:
          '系统管理员在门户里看到的是跨部门知识入口，在工作台里处理的是全局级资料治理、配置与排障，不需要再靠一堆调试页跳来跳去。',
        portalHeaderNote:
          '你当前拥有全局视角，既可以按业务入口查看资料，也可以进入系统级工作台和后台入口。',
        homeFocusTitle: '当前更适合从这三类动作开始',
        homeFocusPoints: [
          '跨部门查看知识资料和 SOP，确认各团队的内容覆盖情况。',
          '通过问答与资料浏览判断知识库是否存在缺口。',
          '进入工作台和管理后台处理全局配置、权限和联调问题。',
        ],
        suggestedQuestions: [
          '不同部门最近更新了哪些关键知识资料？',
          '当前知识库里哪些 SOP 最适合作为统一标准入口？',
          '跨部门常见问题有哪些可以沉淀成统一回答？',
        ],
        myCapabilityItems: [
          '查看全部已授权部门的资料、SOP 和问答结果。',
          '进入工作台处理全局级联调、文档治理和系统排障。',
          '进入管理后台承接身份、权限和后续系统配置模块。',
        ],
        libraryScopeDescription:
          '资料中心可作为全局浏览入口，适合跨部门抽查资料覆盖、更新时间和预览内容。',
        sopScopeDescription:
          'SOP 中心会逐步成为全局标准流程入口，当前可先按部门和分类做浏览与核对。',
        workspaceTitle: '系统级工作台',
        workspaceDescription:
          '工作台不仅承接资料维护，也承接全局联调、跨部门排障和系统管理入口。',
        workspaceBoundary: '你当前拥有全局范围，但仍建议先按部门和分类缩小处理范围。',
        workspaceEntryLabel: '进入系统工作台',
      };
    case 'employee':
    default:
      return {
        roleLabel,
        portalTitle: `先在 ${departmentName} 范围内提问、查 SOP、看资料。`,
        portalDescription:
          '普通员工不需要理解上传、重建向量和系统排障流程。门户只保留业务上真正需要的入口，让你先找到答案和标准流程。',
        portalHeaderNote:
          '你当前使用的是员工视角，系统会自动按部门过滤资料、检索和问答结果。',
        homeFocusTitle: '当前更适合从这三类动作开始',
        homeFocusPoints: [
          '直接提问题，快速拿到带引用的回答。',
          '去 SOP 中心按部门或场景找到标准流程。',
          '在知识库里预览和下载你当前部门已授权的资料。',
        ],
        suggestedQuestions: [
          '设备报警后第一步应该检查什么？',
          '本部门标准开机 SOP 的核心步骤是什么？',
          '新员工上岗前需要阅读哪些资料？',
        ],
        myCapabilityItems: [
          '智能问答、SOP 查看和知识资料浏览。',
          '系统会自动限制到你当前部门的已授权内容。',
          '不会看到内部工作台、全局管理和跨部门运维入口。',
        ],
        libraryScopeDescription:
          '资料中心只展示你当前部门已授权的资料，适合先通过标题、分类和预览确认是否需要下载。',
        sopScopeDescription:
          'SOP 中心优先用于查标准流程，不需要先理解后台任务或文档治理过程。',
        workspaceTitle: '内部工作台',
        workspaceDescription:
          '普通员工不进入内部工作台，上传、治理和排障能力由管理员处理。',
        workspaceBoundary: '当前角色没有工作台入口，只保留知识消费能力。',
        workspaceEntryLabel: '进入工作台',
      };
  }
}
