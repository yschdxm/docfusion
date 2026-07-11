/**
 * 审批对话框组件
 *
 * 负责：
 * - 显示操作摘要和变更预览
 * - 显示风险提示
 * - 提供确认/取消/修改选项
 */

import React, { useState } from 'react';
import { useI18n } from '../../hooks/useI18n';
import Button from '../ui/Button';

interface ApprovalDialogProps {
  requestId: string;
  description: string;
  warnings: string[];
  changesPreview?: {
    type: string;
    before?: string;
    after?: string;
  };
  onApprove: (requestId: string) => void;
  onReject: (requestId: string) => void;
  onModify: (requestId: string, newInstruction: string) => void;
}

export default function ApprovalDialog({
  requestId,
  description,
  warnings,
  changesPreview,
  onApprove,
  onReject,
  onModify
}: ApprovalDialogProps) {
  const { language } = useI18n();
  const [showModifyInput, setShowModifyInput] = useState(false);
  const [modifyInstruction, setModifyInstruction] = useState('');

  const tr = (zh: string, en: string, ja = en) =>
    language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en;

  const handleApprove = () => {
    onApprove(requestId);
  };

  const handleReject = () => {
    onReject(requestId);
  };

  const handleModify = () => {
    if (modifyInstruction.trim()) {
      onModify(requestId, modifyInstruction);
      setShowModifyInput(false);
      setModifyInstruction('');
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-slate-800 rounded-lg shadow-xl max-w-md w-full mx-4 overflow-hidden">
        {/* 头部 */}
        <div className="px-6 py-4 border-b border-slate-700">
          <h3 className="text-lg font-semibold text-white">
            {tr('操作确认', 'Operation Confirmation')}
          </h3>
        </div>

        {/* 内容 */}
        <div className="px-6 py-4 space-y-4">
          {/* 操作描述 */}
          <div>
            <label className="text-sm text-slate-400">
              {tr('操作描述', 'Description')}
            </label>
            <p className="mt-1 text-white">{description}</p>
          </div>

          {/* 警告信息 */}
          {warnings.length > 0 && (
            <div className="bg-yellow-500/10 border border-yellow-500/20 rounded-lg p-3">
              <div className="flex items-center gap-2 text-yellow-400 mb-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                </svg>
                <span className="font-medium">
                  {tr('注意事项', 'Warnings')}
                </span>
              </div>
              <ul className="text-sm text-yellow-300 space-y-1">
                {warnings.map((warning, index) => (
                  <li key={index}>• {warning}</li>
                ))}
              </ul>
            </div>
          )}

          {/* 变更预览 */}
          {changesPreview && (
            <div>
              <label className="text-sm text-slate-400">
                {tr('变更预览', 'Changes Preview')}
              </label>
              <div className="mt-2 bg-slate-900 rounded-lg p-3 text-sm">
                {changesPreview.type === 'text_change' && (
                  <div className="space-y-2">
                    <div>
                      <span className="text-red-400">
                        {tr('原文', 'Before')}:
                      </span>
                      <p className="text-slate-300 mt-1">
                        {changesPreview.before || tr('无', 'None')}
                      </p>
                    </div>
                    <div>
                      <span className="text-green-400">
                        {tr('修改后', 'After')}:
                      </span>
                      <p className="text-slate-300 mt-1">
                        {changesPreview.after || tr('无', 'None')}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 修改指令输入 */}
          {showModifyInput && (
            <div>
              <label className="text-sm text-slate-400">
                {tr('修改指令', 'Modify Instruction')}
              </label>
              <textarea
                value={modifyInstruction}
                onChange={(e) => setModifyInstruction(e.target.value)}
                className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
                rows={3}
                placeholder={tr('输入新的指令...', 'Enter new instruction...')}
              />
            </div>
          )}
        </div>

        {/* 操作按钮 */}
        <div className="px-6 py-4 border-t border-slate-700 flex justify-end gap-3">
          {!showModifyInput ? (
            <>
              <Button
                variant="ghost"
                onClick={handleReject}
              >
                {tr('取消', 'Cancel')}
              </Button>
              <Button
                variant="secondary"
                onClick={() => setShowModifyInput(true)}
              >
                {tr('修改', 'Modify')}
              </Button>
              <Button
                variant="primary"
                onClick={handleApprove}
              >
                {tr('确认执行', 'Confirm')}
              </Button>
            </>
          ) : (
            <>
              <Button
                variant="ghost"
                onClick={() => setShowModifyInput(false)}
              >
                {tr('返回', 'Back')}
              </Button>
              <Button
                variant="primary"
                onClick={handleModify}
                disabled={!modifyInstruction.trim()}
              >
                {tr('提交修改', 'Submit')}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
