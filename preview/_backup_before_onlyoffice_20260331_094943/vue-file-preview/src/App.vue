<template>
  <div class="page">
    <h1>文件上传与文本预览</h1>

    <div class="upload-box">
      <input type="file" @change="handleFileChange" />
      <button @click="handleUpload" :disabled="!selectedFile">上传</button>
    </div>

    <div class="table-box">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>文件名</th>
            <th>类型</th>
            <th>大小(byte)</th>
            <th>上传时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in fileList" :key="item.id">
            <td>{{ item.id }}</td>
            <td>{{ item.fileName }}</td>
            <td>{{ item.suffix }}</td>
            <td>{{ item.fileSize }}</td>
            <td>{{ item.uploadTime }}</td>
            <td class="actions">
              <button @click="handlePreview(item.id)">预览</button>
              <a :href="getDownloadUrl(item.id)" target="_blank">下载</a>
              <button class="danger" @click="handleDelete(item)">删除</button>
            </td>
          </tr>
          <tr v-if="fileList.length === 0">
            <td colspan="6" class="empty">暂无文件</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="previewVisible" class="modal-mask" @click="closePreview">
      <div class="modal" @click.stop>
        <div class="modal-header">
          <span>{{ previewTitle }}</span>
          <button class="close-btn" @click="closePreview">X</button>
        </div>

        <div class="modal-body">
          <iframe
            v-if="previewType === 'pdf'"
            class="pdf-frame"
            :src="previewInlineUrl"
            title="pdf-preview"
          ></iframe>
          <pre v-else-if="previewType !== 'html'">{{ previewContent }}</pre>
          <div v-else class="html-preview" v-html="previewContent"></div>
        </div>

        <div class="modal-footer">
          <span v-if="previewTruncated" class="warn">当前内容已截断显示</span>
          <div class="footer-actions">
            <button v-if="canEditCurrent" @click="openEditor">编辑并保存</button>
            <button @click="closePreview">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="editVisible" class="modal-mask" @click="closeEditor">
      <div class="editor-modal" @click.stop>
        <div class="modal-header">
          <span>编辑文件：{{ previewTitle }}</span>
          <button class="close-btn" @click="closeEditor">X</button>
        </div>

        <div class="editor-body">
          <p class="editor-tip" v-if="previewType === 'html'">
            当前为 HTML 编辑模式。保存后，系统会将该文件转换为 HTML 文件并覆盖原记录。
          </p>
          <textarea v-model="editContent" spellcheck="false"></textarea>
        </div>

        <div class="modal-footer">
          <span></span>
          <div class="footer-actions">
            <button @click="saveEdit" :disabled="saving">{{ saving ? '保存中...' : '保存' }}</button>
            <button @click="closeEditor" :disabled="saving">取消</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  getFileList,
  uploadFile,
  previewFile,
  saveFileContent,
  deleteFile,
  getInlinePreviewUrl,
  getDownloadUrl
} from './api/fileApi'

const selectedFile = ref(null)
const fileList = ref([])

const previewVisible = ref(false)
const previewTitle = ref('')
const previewType = ref('text')
const previewContent = ref('')
const previewInlineUrl = ref('')
const previewTruncated = ref(false)
const currentPreviewId = ref(null)

const editVisible = ref(false)
const editContent = ref('')
const saving = ref(false)

const canEditCurrent = computed(() => previewType.value !== 'pdf')

function handleFileChange(event) {
  const files = event.target.files
  if (files && files.length > 0) {
    selectedFile.value = files[0]
  }
}

async function handleUpload() {
  if (!selectedFile.value) {
    alert('请先选择文件')
    return
  }

  try {
    const res = await uploadFile(selectedFile.value)
    if (res.data.code === 200) {
      alert('上传成功')
      selectedFile.value = null
      await loadFileList()
    } else {
      alert(res.data.message || '上传失败')
    }
  } catch (error) {
    console.error(error)
    alert('上传失败')
  }
}

async function loadFileList() {
  try {
    const res = await getFileList()
    if (res.data.code === 200) {
      fileList.value = res.data.data || []
    }
  } catch (error) {
    console.error(error)
  }
}

async function handlePreview(id) {
  try {
    const res = await previewFile(id)
    if (res.data.code === 200) {
      const data = res.data.data
      previewTitle.value = data.fileName
      previewType.value = data.previewType || 'text'
      previewContent.value = data.content || ''
      previewInlineUrl.value = previewType.value === 'pdf' ? getInlinePreviewUrl(id) : ''
      previewTruncated.value = data.truncated
      currentPreviewId.value = id
      previewVisible.value = true
    } else {
      alert(res.data.message || '预览失败')
    }
  } catch (error) {
    console.error(error)
    alert('预览失败')
  }
}

function openEditor() {
  editContent.value = previewContent.value || ''
  editVisible.value = true
}

function closeEditor() {
  if (saving.value) {
    return
  }
  editVisible.value = false
  editContent.value = ''
}

async function saveEdit() {
  if (!currentPreviewId.value) {
    return
  }

  saving.value = true
  try {
    const res = await saveFileContent(currentPreviewId.value, {
      content: editContent.value,
      previewType: previewType.value
    })

    if (res.data.code === 200) {
      alert('保存成功')
      previewContent.value = editContent.value
      previewTruncated.value = false
      editVisible.value = false
      await loadFileList()
    } else {
      alert(res.data.message || '保存失败')
    }
  } catch (error) {
    console.error(error)
    alert('保存失败')
  } finally {
    saving.value = false
  }
}

async function handleDelete(item) {
  const ok = window.confirm(`确认删除文件「${item.fileName}」吗？`)
  if (!ok) {
    return
  }

  try {
    const res = await deleteFile(item.id)
    if (res.data.code === 200) {
      alert('删除成功')
      if (previewVisible.value && currentPreviewId.value === item.id) {
        closePreview()
      }
      await loadFileList()
    } else {
      alert(res.data.message || '删除失败')
    }
  } catch (error) {
    console.error(error)
    alert('删除失败')
  }
}

function closePreview() {
  previewVisible.value = false
  previewTitle.value = ''
  previewType.value = 'text'
  previewContent.value = ''
  previewInlineUrl.value = ''
  previewTruncated.value = false
  currentPreviewId.value = null
  closeEditor()
}

onMounted(() => {
  loadFileList()
})
</script>

<style scoped>
.page {
  width: 1000px;
  margin: 30px auto;
  font-family: Arial, sans-serif;
}

h1 {
  margin-bottom: 20px;
}

.upload-box {
  margin-bottom: 20px;
  display: flex;
  gap: 12px;
  align-items: center;
}

button {
  padding: 6px 14px;
  cursor: pointer;
}

.table-box {
  border: 1px solid #ddd;
  border-radius: 6px;
  overflow: hidden;
}

table {
  width: 100%;
  border-collapse: collapse;
  background: #fff;
}

th,
td {
  border-bottom: 1px solid #eee;
  padding: 12px;
  text-align: left;
  font-size: 14px;
}

th {
  background: #f7f7f7;
}

.actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.empty {
  text-align: center;
  color: #999;
}

a {
  color: #409eff;
  text-decoration: none;
}

.danger {
  color: #fff;
  background: #d9534f;
  border: 1px solid #c9302c;
}

.modal-mask {
  position: fixed;
  left: 0;
  top: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 999;
}

.modal,
.editor-modal {
  width: 980px;
  max-width: 94vw;
  height: 80vh;
  background: #fff;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.editor-modal {
  width: 1000px;
}

.modal-header {
  height: 50px;
  padding: 0 16px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: bold;
}

.close-btn {
  border: none;
  background: transparent;
  font-size: 16px;
}

.modal-body,
.editor-body {
  flex: 1;
  overflow: auto;
  padding: 16px;
  background: #fafafa;
}

.editor-tip {
  margin: 0 0 10px;
  color: #e67e22;
  font-size: 13px;
}

.editor-body textarea {
  width: 100%;
  height: calc(100% - 10px);
  border: 1px solid #ddd;
  border-radius: 6px;
  padding: 12px;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.6;
  resize: none;
  box-sizing: border-box;
}

.pdf-frame {
  width: 100%;
  height: 100%;
  min-height: 560px;
  border: none;
  background: #fff;
}

.modal-body pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.6;
}

:deep(.html-preview) {
  color: #222;
  font-size: 14px;
  line-height: 1.7;
}

:deep(.html-preview p) {
  margin: 0 0 12px;
}

:deep(.html-preview .docx-image) {
  display: block;
  max-width: 100%;
  margin: 10px 0;
  border: 1px solid #eee;
}

:deep(.html-preview .ppt-image) {
  display: inline-block;
  max-width: 320px;
  max-height: 180px;
  width: auto;
  height: auto;
  margin: 6px 8px 10px 0;
  border: 1px solid #eee;
  object-fit: contain;
  background: #fff;
}

:deep(.html-preview .ppt-slide) {
  padding: 12px;
  margin-bottom: 14px;
  border: 1px solid #e5e5e5;
  border-radius: 8px;
  background: #fff;
}

:deep(.html-preview .docx-table) {
  width: 100%;
  border-collapse: collapse;
  margin: 10px 0 14px;
  background: #fff;
}

:deep(.html-preview .docx-table td) {
  border: 1px solid #ddd;
  padding: 6px 8px;
  vertical-align: top;
}

:deep(.html-preview .preview-note),
:deep(.html-preview .image-note) {
  color: #e67e22;
}

.modal-footer {
  height: 50px;
  padding: 0 16px;
  border-top: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.footer-actions {
  display: flex;
  gap: 8px;
}

.warn {
  color: #e67e22;
  font-size: 13px;
}
</style>