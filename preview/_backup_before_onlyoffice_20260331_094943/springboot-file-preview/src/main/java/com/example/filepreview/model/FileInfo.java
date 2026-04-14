package com.example.filepreview.model;

public class FileInfo {
    private Long id;
    private String fileName;
    private String filePath;
    private String suffix;
    private Long fileSize;
    private String uploadTime;

    public FileInfo() {
    }

    public FileInfo(Long id, String fileName, String filePath, String suffix, Long fileSize, String uploadTime) {
        this.id = id;
        this.fileName = fileName;
        this.filePath = filePath;
        this.suffix = suffix;
        this.fileSize = fileSize;
        this.uploadTime = uploadTime;
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getFileName() {
        return fileName;
    }

    public void setFileName(String fileName) {
        this.fileName = fileName;
    }

    public String getFilePath() {
        return filePath;
    }

    public void setFilePath(String filePath) {
        this.filePath = filePath;
    }

    public String getSuffix() {
        return suffix;
    }

    public void setSuffix(String suffix) {
        this.suffix = suffix;
    }

    public Long getFileSize() {
        return fileSize;
    }

    public void setFileSize(Long fileSize) {
        this.fileSize = fileSize;
    }

    public String getUploadTime() {
        return uploadTime;
    }

    public void setUploadTime(String uploadTime) {
        this.uploadTime = uploadTime;
    }
}
