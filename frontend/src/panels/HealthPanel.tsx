/**
 * 健康检查面板组件
 * 用于检查后端服务状态和配置信息
 */

import { useState } from 'react';
import { Activity } from 'lucide-react';  // 引入图标。
import { Card, Button, StatusPill, ResultBox } from '@/components';
import { formatApiError, getHealth, type HealthResponse } from '@/api';

// 面板状态类型定义。
type PanelStatus = 'idle' | 'loading' | 'success' | 'error';

export function HealthPanel() {
  // 状态管理。
  const [status, setStatus] = useState<PanelStatus>('idle');
  const [data, setData] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string>('');

  // 执行健康检查。
  const handleCheck = async () => {
    setStatus('loading');
    setError('');

    try {
      const result = await getHealth();
      setData(result);
      setStatus('success');
    } catch (err) {
      setError(formatApiError(err, '健康检查'));
      setStatus('error');
    }
  };

  // 状态文本映射。
  const statusText = {
    idle: '待执行',
    loading: '正在检查后端',
    success: '后端可访问',
    error: '健康检查失败',
  };

  // 状态色调映射。
  const statusTone: Record<PanelStatus, 'default' | 'ok' | 'warn' | 'error'> = {
    idle: 'default',
    loading: 'warn',
    success: 'ok',
    error: 'error',
  };

  return (
    <Card className="col-span-4">
      {/* 标题 */}
      <h2 className="m-0 mb-1.5 text-xl font-semibold text-ink">健康检查</h2>
      <p className="m-0 mb-4 text-ink-soft leading-relaxed">
        读取当前后端配置，确认向量库、模型和队列服务的实际提供方。
      </p>

      {/* 操作按钮 */}
      <div className="flex flex-wrap gap-2.5 mb-4">
        <Button onClick={handleCheck} loading={status === 'loading'}>
          <span className="flex items-center gap-2">
            <Activity className="w-4 h-4" />
            检查后端状态
          </span>
        </Button>
      </div>

      {/* 状态徽章 */}
      <StatusPill tone={statusTone[status]}>{statusText[status]}</StatusPill>

      {/* 结果展示 */}
      <div className="mt-4">
        <ResultBox>
          {data ? (
            JSON.stringify(data, null, 2)
          ) : error ? (
            error
          ) : (
            '点击健康检查后，这里会显示当前后端的实时配置。'
          )}
        </ResultBox>
      </div>
    </Card>
  );
}
