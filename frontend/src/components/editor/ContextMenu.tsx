/**
 * 右键菜单组件
 *
 * 负责：
 * - 显示智能操作菜单
 * - 处理菜单项点击
 */

import React, { useState, useEffect, useRef } from 'react';
import { useI18n } from '../../hooks/useI18n';

interface ContextMenuProps {
  x: number;
  y: number;
  selectedText: string;
  onAction: (action: string, customInstruction?: string) => void;
  onClose: () => void;
}

export default function ContextMenu({
  x,
  y,
  selectedText,
  onAction,
  onClose
}: ContextMenuProps) {
  const { language } = useI18n();
  const menuRef = useRef<HTMLDivElement>(null);
  const [showCustomInput, setShowCustomInput] = useState(false);
  const [customInstruction, setCustomInstruction] = useState('');

  const tr = (zh: string, en: string, ja = en) =>
    language === 'zh-CN' ? zh : language === 'ja-JP' ? ja : en;

  // 点击外部关闭菜单
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        onClose();
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [onClose]);

  // 调整菜单位置，确保不超出视窗
  useEffect(() => {
    if (menuRef.current) {
      const rect = menuRef.current.getBoundingClientRect();
      const viewportWidth = window.innerWidth;
      const viewportHeight = window.innerHeight;

      if (x + rect.width > viewportWidth) {
        menuRef.current.style.left = `${viewportWidth - rect.width - 10}px`;
      }
      if (y + rect.height > viewportHeight) {
        menuRef.current.style.top = `${viewportHeight - rect.height - 10}px`;
      }
    }
  }, [x, y]);

  const handleAction = (action: string) => {
    if (action === 'custom') {
      setShowCustomInput(true);
    } else {
      onAction(action);
      onClose();
    }
  };

  const handleCustomSubmit = () => {
    if (customInstruction.trim()) {
      onAction('custom', customInstruction);
      onClose();
    }
  };

  const menuItems = [
    {
      id: 'rewrite',
      label: tr('智能改写', 'Smart Rewrite'),
      icon: '✏️'
    },
    {
      id: 'translate',
      label: tr('翻译', 'Translate'),
      icon: '🌐'
    },
    {
      id: 'summarize',
      label: tr('总结', 'Summarize'),
      icon: '📝'
    },
    {
      id: 'extract',
      label: tr('提取信息', 'Extract Info'),
      icon: '📊'
    },
    {
      id: 'format',
      label: tr('格式调整', 'Format'),
      icon: '🎨'
    },
    {
      id: 'custom',
      label: tr('自定义指令', 'Custom Instruction'),
      icon: '⚙️'
    }
  ];

  return (
    <div
      ref={menuRef}
      className="fixed bg-slate-800 border border-slate-700 rounded-lg shadow-xl py-1 min-w-[200px] z-50"
      style={{ left: x, top: y }}
    >
      {/* 标题 */}
      <div className="px-3 py-2 border-b border-slate-700">
        <div className="text-xs text-slate-400">
          {tr('智能操作', 'Smart Actions')}
        </div>
        <div className="text-sm text-slate-300 truncate mt-1">
          {selectedText.substring(0, 50)}{selectedText.length > 50 ? '...' : ''}
        </div>
      </div>

      {/* 自定义指令输入 */}
      {showCustomInput ? (
        <div className="px-3 py-2">
          <textarea
            value={customInstruction}
            onChange={(e) => setCustomInstruction(e.target.value)}
            className="w-full bg-slate-900 border border-slate-700 rounded px-2 py-1 text-sm text-white focus:outline-none focus:border-blue-500"
            rows={3}
            placeholder={tr('输入自定义指令...', 'Enter custom instruction...')}
            autoFocus
          />
          <div className="flex justify-end gap-2 mt-2">
            <button
              className="px-2 py-1 text-xs text-slate-400 hover:text-white"
              onClick={() => setShowCustomInput(false)}
            >
              {tr('取消', 'Cancel')}
            </button>
            <button
              className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700"
              onClick={handleCustomSubmit}
              disabled={!customInstruction.trim()}
            >
              {tr('执行', 'Execute')}
            </button>
          </div>
        </div>
      ) : (
        /* 菜单项 */
        <div className="py-1">
          {menuItems.map((item) => (
            <button
              key={item.id}
              className="w-full px-3 py-2 text-left text-sm text-slate-300 hover:bg-slate-700 flex items-center gap-2"
              onClick={() => handleAction(item.id)}
            >
              <span>{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
