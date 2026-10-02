{{- define "inference.labels" -}}
app.kubernetes.io/part-of: goodput-stack
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end -}}

{{- define "inference.llamacpp.name" -}}
{{ .Release.Name }}-llamacpp
{{- end -}}

{{- define "inference.llamacpp.selector" -}}
app.kubernetes.io/name: llamacpp
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}
