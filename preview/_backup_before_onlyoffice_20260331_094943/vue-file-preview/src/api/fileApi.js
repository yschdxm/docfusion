import axios from 'axios'

const request = axios.create({
  baseURL: 'http://localhost:8080/api',
  timeout: 10000
})

export function uploadFile(file) {
  const formData = new FormData()
  formData.append('file', file)

  return request.post('/files/upload', formData, {
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