import axios from 'axios'

const request = axios.create({
  baseURL: 'http://localhost:8080/api',
  timeout: 60000
})

export function uploadFile(file) {
  const formData = new FormData()
  formData.append('file', file)

  return request.post('/files/upload', formData, {
    timeout: 180000,
    headers: {
      'Content-Type': 'multipart/form-data'
    }
  })
}

export function getFileList() {
  return request.get('/files')
}

export function previewFile(id) {
  return request.get(`/files/${id}/preview`)
}

export function getOnlyOfficeConfig(id, mode = 'view') {
  return request.get(`/files/${id}/office-config`, { params: { mode } })
}

export function saveFileContent(id, payload) {
  return request.post(`/files/${id}/save`, payload)
}

export function deleteFile(id) {
  return request.delete(`/files/${id}`)
}

export function getInlinePreviewUrl(id) {
  return `http://localhost:8080/api/files/${id}/inline`
}

export function getDownloadUrl(id) {
  return `http://localhost:8080/api/files/${id}/download`
}