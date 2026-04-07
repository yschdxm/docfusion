package com.example.filepreview.model;

public class FilePreviewResponse {
    private String fileName;
    private String previewType;
    private String content;
    private boolean truncated;

    public FilePreviewResponse() {
    }

    public FilePreviewResponse(String fileName, String previewType, String content, boolean truncated) {
        this.fileName = fileName;
        this.previewType = previewType;
        this.content = content;
        this.truncated = truncated;
    }

    public String getFileName() {
        return fileName;
    }

    public void setFileName(String fileName) {
        this.fileName = fileName;
    }

    public String getPreviewType() {
        return previewType;
    }

    public void setPreviewType(String previewType) {
        this.previewType = previewType;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public boolean isTruncated() {
        return truncated;
    }

    public void setTruncated(boolean truncated) {
        this.truncated = truncated;
    }
}
