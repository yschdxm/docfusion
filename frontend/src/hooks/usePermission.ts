/**
 * 权限管理Hook
 *
 * 负责：
 * - 检查工具执行权限
 * - 管理用户偏好
 * - 处理审批流程
 */

import { useState, useCallback } from 'react';
import api from '../services/api';

interface PermissionCheckResult {
  allowed: boolean;
  requiresApproval: boolean;
  requestId?: string;
  description?: string;
  warnings?: string[];
  changesPreview?: any;
}

interface ApprovalResponse {
  requestId: string;
  approved: boolean;
  modifiedParams?: any;
  userMessage?: string;
}

export function usePermission() {
  const [autoApprovedTools, setAutoApprovedTools] = useState<Set<string>>(
    new Set(JSON.parse(localStorage.getItem('auto_approved_tools') || '[]'))
  );

  /**
   * 检查工具执行权限
   */
  const checkPermission = useCallback(async (
    toolName: string,
    toolParams: any,
    permissionLevel: 'safe' | 'sensitive' | 'dangerous'
  ): Promise<PermissionCheckResult> => {
    // 安全工具 - 自动允许
    if (permissionLevel === 'safe') {
      return { allowed: true, requiresApproval: false };
    }

    // 检查用户偏好
    if (autoApprovedTools.has(toolName)) {
      return { allowed: true, requiresApproval: false };
    }

    // 危险工具 - 需要确认
    if (permissionLevel === 'dangerous') {
      const request = await createApprovalRequest(toolName, toolParams, permissionLevel);
      return {
        allowed: false,
        requiresApproval: true,
        requestId: request.request_id,
        description: request.description,
        warnings: request.warnings,
        changesPreview: request.changes_preview
      };
    }

    // 敏感工具 - 询问用户
    const request = await createApprovalRequest(toolName, toolParams, permissionLevel);
    return {
      allowed: false,
      requiresApproval: true,
      requestId: request.request_id,
      description: request.description,
      warnings: request.warnings,
      changesPreview: request.changes_preview
    };
  }, [autoApprovedTools]);

  /**
   * 创建审批请求
   */
  const createApprovalRequest = async (
    toolName: string,
    toolParams: any,
    permissionLevel: string
  ) => {
    const response = await api.post('/interaction/approval-request', {
      tool_name: toolName,
      tool_params: toolParams,
      permission_level: permissionLevel
    });
    return response.data;
  };

  /**
   * 提交审批响应
   */
  const submitApproval = useCallback(async (response: ApprovalResponse): Promise<boolean> => {
    try {
      await api.post('/interaction/approve', {
        request_id: response.requestId,
        approved: response.approved,
        modified_params: response.modifiedParams,
        user_message: response.userMessage
      });
      return true;
    } catch (error) {
      console.error('提交审批失败:', error);
      return false;
    }
  }, []);

  /**
   * 自动批准工具
   */
  const autoApproveTool = useCallback((toolName: string) => {
    const newSet = new Set(autoApprovedTools);
    newSet.add(toolName);
    setAutoApprovedTools(newSet);
    localStorage.setItem('auto_approved_tools', JSON.stringify([...newSet]));
  }, [autoApprovedTools]);

  /**
   * 撤销自动批准
   */
  const revokeAutoApproval = useCallback((toolName: string) => {
    const newSet = new Set(autoApprovedTools);
    newSet.delete(toolName);
    setAutoApprovedTools(newSet);
    localStorage.setItem('auto_approved_tools', JSON.stringify([...newSet]));
  }, [autoApprovedTools]);

  return {
    checkPermission,
    submitApproval,
    autoApproveTool,
    revokeAutoApproval,
    autoApprovedTools
  };
}
