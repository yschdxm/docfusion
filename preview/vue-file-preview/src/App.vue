<template>
  <div class="page">
    <h1>文件上传与预览</h1>

    <div class="upload-box card">
      <input type="file" @change="handleFileChange" />
      <button @click="handleUpload" :disabled="!selectedFile">上传</button>
    </div>

    <div class="table-box card">
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

    <div v-if="previewVisible" class="modal-mask">
      <div class="modal" :class="{ 'is-fullscreen': previewFullscreen }" @click.stop>
        <div class="modal-header">
          <span>{{ previewTitle }}</span>
          <div class="header-actions">
            <button
              class="header-btn icon-btn"
              @click="togglePreviewSize"
              :title="previewFullscreen ? '切换为半屏' : '切换为全屏'"
              aria-label="切换预览尺寸"
            >
              <span v-if="previewFullscreen">🗗</span>
              <span v-else>⛶</span>
            </button>
            <button class="close-btn" @click="closePreview">X</button>
          </div>
        </div>

        <div class="modal-body">
          <div v-if="previewType === 'onlyoffice'" class="office-wrap">
            <div v-if="officeLoading" class="office-tip">正在加载在线文档组件...</div>
            <div v-if="officeError" class="office-tip office-error">{{ officeError }}</div>
            <div id="onlyoffice-editor" class="office-editor"></div>
          </div>

          <iframe v-else-if="previewType === 'pdf'" class="pdf-frame" :src="previewInlineUrl" title="pdf-preview"></iframe>

          <pre v-else-if="previewType !== 'html'">{{ previewContent }}</pre>
          <div v-else class="html-preview" v-html="previewContent"></div>
        </div>

        <div class="modal-footer">
          <span v-if="previewTruncated" class="warn">当前内容已截断显示</span>
          <div class="footer-actions">
            <button v-if="previewType === 'onlyoffice'" @click="switchOfficeMode">
              {{ officeMode === 'edit' ? '切到只读' : '进入编辑' }}
            </button>
            <button v-if="canEditText" @click="openEditor">编辑并保存</button>
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
  getOnlyOfficeConfig,
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
const previewFullscreen = ref(false)

const officeMode = ref('view')
const officeLoading = ref(false)
const officeError = ref('')
let officeEditorInstance = null
let loadedOnlyOfficeScript = null

const editVisible = ref(false)
const editContent = ref('')
const saving = ref(false)

const canEditText = computed(() => previewType.value === 'text' || previewType.value === 'html')

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
    if (res.data.code !== 200) {
      alert(res.data.message || '预览失败')
      return
    }

    const data = res.data.data
    previewTitle.value = data.fileName
    previewType.value = data.previewType || 'text'
    previewContent.value = data.content || ''
    previewInlineUrl.value = previewType.value === 'pdf' ? getInlinePreviewUrl(id) : ''
    previewTruncated.value = data.truncated
    currentPreviewId.value = id
    previewVisible.value = true

    if (previewType.value === 'onlyoffice') {
      officeMode.value = 'view'
      await mountOnlyOffice('view')
    }
  } catch (error) {
    console.error(error)
    alert('预览失败')
  }
}

async function switchOfficeMode() {
  if (!currentPreviewId.value) {
    return
  }
  const targetMode = officeMode.value === 'edit' ? 'view' : 'edit'
  officeMode.value = targetMode
  await mountOnlyOffice(targetMode)
}

async function mountOnlyOffice(mode) {
  if (!currentPreviewId.value) {
    return
  }

  officeLoading.value = true
  officeError.value = ''
  destroyOnlyOfficeEditor()

  try {
    const res = await getOnlyOfficeConfig(currentPreviewId.value, mode)
    if (res.data.code !== 200) {
      throw new Error(res.data.message || '获取 OnlyOffice 配置失败')
    }

    const payload = res.data.data
    const serverUrl = payload.serverUrl
    const config = payload.config

    await ensureOnlyOfficeScript(serverUrl)

    if (!window.DocsAPI || !window.DocsAPI.DocEditor) {
      throw new Error('OnlyOffice 脚本加载失败，请检查 Document Server 是否启动')
    }

    officeEditorInstance = new window.DocsAPI.DocEditor('onlyoffice-editor', config)
  } catch (err) {
    console.error(err)
    officeError.value = err.message || 'OnlyOffice 加载失败'
  } finally {
    officeLoading.value = false
  }
}

function ensureOnlyOfficeScript(serverUrl) {
  if (window.DocsAPI && window.DocsAPI.DocEditor) {
    return Promise.resolve()
  }

  const normalized = serverUrl.endsWith('/') ? serverUrl.slice(0, -1) : serverUrl
  const src = `${normalized}/web-apps/apps/api/documents/api.js`

  if (loadedOnlyOfficeScript && loadedOnlyOfficeScript !== src) {
    const oldScript = document.querySelector(`script[src="${loadedOnlyOfficeScript}"]`)
    if (oldScript) {
      oldScript.remove()
    }
    loadedOnlyOfficeScript = null
  }

  return new Promise((resolve, reject) => {
    let script = document.querySelector(`script[src="${src}"]`)
    if (!script) {
      script = document.createElement('script')
      script.src = src
      document.body.appendChild(script)
      loadedOnlyOfficeScript = src
    }

    const start = Date.now()
    const timer = setInterval(() => {
      if (window.DocsAPI && window.DocsAPI.DocEditor) {
        clearInterval(timer)
        resolve()
        return
      }

      if (Date.now() - start > 60000) {
        clearInterval(timer)
        if (script && script.parentNode) {
          script.parentNode.removeChild(script)
        }
        loadedOnlyOfficeScript = null
        reject(new Error('OnlyOffice 脚本加载超时，请确认 http://localhost:8088 可访问'))
      }
    }, 200)

    script.onerror = () => {
      clearInterval(timer)
      if (script && script.parentNode) {
        script.parentNode.removeChild(script)
      }
      loadedOnlyOfficeScript = null
      reject(new Error('OnlyOffice 脚本加载失败，请检查 Document Server 是否启动'))
    }
  })
}

function destroyOnlyOfficeEditor() {
  if (officeEditorInstance && typeof officeEditorInstance.destroyEditor === 'function') {
    officeEditorInstance.destroyEditor()
  }
  officeEditorInstance = null
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

function togglePreviewSize() {
  previewFullscreen.value = !previewFullscreen.value
}

function closePreview() {
  destroyOnlyOfficeEditor()
  previewVisible.value = false
  previewTitle.value = ''
  previewType.value = 'text'
  previewContent.value = ''
  previewInlineUrl.value = ''
  previewTruncated.value = false
  currentPreviewId.value = null
  officeMode.value = 'view'
  officeLoading.value = false
  officeError.value = ''
  previewFullscreen.value = false
  closeEditor()
}

onMounted(() => {
  loadFileList()
})
</script>
