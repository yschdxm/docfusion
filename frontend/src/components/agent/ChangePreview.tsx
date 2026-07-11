/**
 * 变更预览组件
 *
 * 负责：
 * - 以diff形式显示变更
 * - 提供应用/取消/微调操作
 */

import React, { useState } from 'react';
import { useI18n } from '../../hooks/useI18n';
import Button from '../ui/Button';

interface ChangeItem {
  location: string;
  before: string;
  after: string;
  changeType: 'add' | 'modify' | 'delete';
}

interface ChangePreviewProps {
  title: string;
  description: string;
  changes: ChangeItem[];
  onApply: () => void;
  onCancel: () => void;
  onRefine: (instruction: string) => void;
}

export default function ChangePreview({
  title,
  description,
  changes,
  onApply,
  onCancel,
  onRefine
}: ChangePreviewProps) {
  const { language } = useI18n();
  const [showRefineInput, setShowRefineInput] = useState(false);
  const [refineInstruction, setRefineInstruction] = useState('');

  const tr = (zh: string, en: string, ja = en) =>
    language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en;

  const handleRefine = () => {
    if (refineInstruction.trim()) {
      onRefine(refineInstruction);
      setShowRefineInput(false);
      setRefineInstruction('');
    }
  };

  const getChangeTypeColor = (type: string) => {
    switch (type) {
      case 'add':
        return 'text-green-400 bg-green-400/10';
      case 'delete':
        return 'text-red-400 bg-red-400/10';
      case 'modify':
        return 'text-yellow-400 bg-yellow-400/10';
      default:
        return 'text-slate-400 bg-slate-400/10';
    }
  };

  const getChangeTypeLabel = (type: string) => {
    switch (type) {
      case 'add':
        return tr('新增', 'Add');
      case 'delete':
        return tr('删除', 'Delete');
      case 'modify':
        return tr('修改', 'Modify');
      default:
        return type;
    }
  };

  return (
    <div className="bg-slate-800 rounded-lg shadow-xl overflow-hidden">
      {/* 头部 */}
      <div className="px-4 py-3 border-b border-slate-700">
        <h4 className="font-medium text-white">{title}</h4>
        <p className="text-sm text-slate-400 mt-1">{description}</p>
      </div>

      {/* 变更列表 */}
      <div className="max-h-96 overflow-y-auto">
        {changes.map((change, index) => (
          <div
            key={index}
            className="border-b border-slate-700 last:border-b-0"
          >
            {/* 位置信息 */}
            <div className="px-4 py-2 bg-slate-750 flex items-center justify-between">
              <span className="text-sm text-slate-300">
                {change.location}
              </span>
              <span className={`text-xs px-2 py-1 rounded ${getChangeTypeColor(change.changeType)}`}>
                {getChangeTypeLabel(change.changeType)}
              </span>
            </div>

            {/* Diff显示 */}
            <div className="px-4 py-3 grid grid-cols-2 gap-4">
              {/* 原文 */}
              <div>
                <div className="text-xs text-red-400 mb-1">
                  {tr('原文', 'Before')}
                </div>
                <div className="bg-red-500/10 rounded p-2 text-sm text-slate-300 font-mono whitespace-pre-wrap">
                  {change.before || tr('（空）', '(empty)')}
                </div>
              </div>

              {/* 修改后 */}
              <div>
                <div className="text-xs text-green-400 mb-1">
                  {tr('修改后', 'After')}
                </div>
                <div className="bg-green-500/10 rounded p-2 text-sm text-slate-300 font-mono whitespace-pre-wrap">
                  {change.after || tr('（空）', '(empty)')}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* 微调输入 */}
      {showRefineInput && (
        <div className="px-4 py-3 border-t border-slate-700">
          <label className="text-sm text-slate-400">
            {tr('微调指令', 'Refine Instruction')}
          </label>
          <textarea
            value={refineInstruction}
            onChange={(e) => setRefineInstruction(e.target.value)}
            className="mt-1 w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-blue-500"
            rows={2}
            placeholder={tr('输入微调指令...', 'Enter refine instruction...')}
          />
        </div>
      )}

      {/* 操作按钮 */}
      <div className="px-4 py-3 border-t border-slate-700 flex justify-end gap-3">
        {!showRefineInput ? (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={onCancel}
            >
              {tr('取消', 'Cancel')}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setShowRefineInput(true)}
            >
              {tr('微调', 'Refine')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={onApply}
            >
              {tr('应用', 'Apply')}
            </Button>
          </>
        ) : (
          <>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setShowRefineInput(false)}
            >
              {tr('返回', 'Back')}
            </Button>
            <Button
              variant="primary"
              size="sm"
              onClick={handleRefine}
              disabled={!refineInstruction.trim()}
            >
              {tr('提交', 'Submit')}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
