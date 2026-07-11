/**
 * AgentBridge服务 - 连接OnlyOffice编辑器和Agent系统
 *
 * 负责：
 * - 封装OnlyOffice Editor API
 * - 提供选区读取/替换
 * - 提供单元格操作
 * - 提供文档结构获取
 */

class AgentBridgeService {
  private editor: any = null;
  private documentId: string = '';

  /**
   * 初始化桥接服务
   */
  initialize(editor: any, documentId: string): void {
    this.editor = editor;
    this.documentId = documentId;
  }

  /**
   * 获取当前选区内容
   */
  getSelection(): Promise<{
    text: string;
    startOffset?: number;
    endOffset?: number;
    paragraphIndex?: number;
  } | null> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(null);
        return;
      }

      try {
        // OnlyOffice API获取选区
        this.editor.getSelection((selection: any) => {
          if (selection && selection.text) {
            resolve({
              text: selection.text,
              startOffset: selection.startOffset,
              endOffset: selection.endOffset,
              paragraphIndex: selection.paragraphIndex
            });
          } else {
            resolve(null);
          }
        });
      } catch (error) {
        console.error('获取选区失败:', error);
        resolve(null);
      }
    });
  }

  /**
   * 替换选区内容
   */
  replaceSelection(text: string, preserveFormat: boolean = true): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(false);
        return;
      }

      try {
        this.editor.replaceSelectedText(text, preserveFormat, (result: boolean) => {
          resolve(result);
        });
      } catch (error) {
        console.error('替换选区失败:', error);
        resolve(false);
      }
    });
  }

  /**
   * 在光标位置插入内容
   */
  insertAtCursor(text: string): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(false);
        return;
      }

      try {
        this.editor.insertText(text, (result: boolean) => {
          resolve(result);
        });
      } catch (error) {
        console.error('插入内容失败:', error);
        resolve(false);
      }
    });
  }

  /**
   * 获取Excel单元格值
   */
  getCellValue(sheetName: string, row: number, col: number): Promise<any> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(null);
        return;
      }

      try {
        // OnlyOffice API获取单元格值
        this.editor.getCellValue(sheetName, row, col, (value: any) => {
          resolve(value);
        });
      } catch (error) {
        console.error('获取单元格值失败:', error);
        resolve(null);
      }
    });
  }

  /**
   * 设置Excel单元格值
   */
  setCellValue(sheetName: string, row: number, col: number, value: any): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(false);
        return;
      }

      try {
        this.editor.setCellValue(sheetName, row, col, value, (result: boolean) => {
          resolve(result);
        });
      } catch (error) {
        console.error('设置单元格值失败:', error);
        resolve(false);
      }
    });
  }

  /**
   * 获取文档结构
   */
  getDocumentStructure(): Promise<{
    title: string;
    headings: Array<{ level: number; text: string; index: number }>;
    paragraphs: number;
    tables: number;
  } | null> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(null);
        return;
      }

      try {
        this.editor.getDocumentStructure((structure: any) => {
          resolve(structure);
        });
      } catch (error) {
        console.error('获取文档结构失败:', error);
        resolve(null);
      }
    });
  }

  /**
   * 应用文本格式
   */
  applyFormat(format: {
    bold?: boolean;
    italic?: boolean;
    fontSize?: number;
    fontFamily?: string;
    color?: string;
  }): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(false);
        return;
      }

      try {
        this.editor.applyTextFormat(format, (result: boolean) => {
          resolve(result);
        });
      } catch (error) {
        console.error('应用格式失败:', error);
        resolve(false);
      }
    });
  }

  /**
   * 撤销操作
   */
  undo(): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(false);
        return;
      }

      try {
        this.editor.undo((result: boolean) => {
          resolve(result);
        });
      } catch (error) {
        console.error('撤销失败:', error);
        resolve(false);
      }
    });
  }

  /**
   * 重做操作
   */
  redo(): Promise<boolean> {
    return new Promise((resolve) => {
      if (!this.editor) {
        resolve(false);
        return;
      }

      try {
        this.editor.redo((result: boolean) => {
          resolve(result);
        });
      } catch (error) {
        console.error('重做失败:', error);
        resolve(false);
      }
    });
  }

  /**
   * 清理资源
   */
  destroy(): void {
    this.editor = null;
    this.documentId = '';
  }
}

// 导出单例
export const agentBridgeService = new AgentBridgeService();
