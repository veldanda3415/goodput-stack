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

{{- define "inference.sim.name" -}}
{{ .Release.Name }}-vllm-sim
{{- end -}}

{{- define "inference.sim.selector" -}}
app.kubernetes.io/name: vllm-sim
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Ingress-only NetworkPolicy for one backend. Call with a dict:
  root     - the top-level context ($)
  name     - policy name (= the backend's Deployment name)
  selector - the backend's rendered selector labels (YAML string)
  port     - the server port to open
Once Ingress is listed in policyTypes, the selected pods drop all inbound traffic except what
the rules allow. Policies only ever ALLOW; several selecting the same pod add up (union).
*/}}
{{- define "inference.networkPolicy" -}}
{{- $np := .root.Values.networkPolicy -}}
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: {{ .name }}
  labels:
    {{- include "inference.labels" .root | nindent 4 }}
    {{- .selector | nindent 4 }}
spec:
  # Which pods this policy protects: this backend's server pods in this release.
  podSelector:
    matchLabels:
      {{- .selector | nindent 6 }}
  policyTypes:
    - Ingress            # inbound only; outbound (egress) stays unrestricted
  ingress:
    {{- if or $np.allowFrom $np.allowFromNamespaces }}
    - from:
        # One podSelector per allowFrom item: a pod matching ANY of them is allowed.
        # podSelector alone (no namespaceSelector) = only pods in THIS namespace.
        {{- range $np.allowFrom }}
        - podSelector:
            matchLabels:
              {{- toYaml . | nindent 14 }}
        {{- end }}
        # allowFromNamespaces: pods matching podLabels in the named namespace (one peer = both must match).
        {{- range $np.allowFromNamespaces }}
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: {{ .namespace }}
          podSelector:
            matchLabels:
              {{- toYaml .podLabels | nindent 14 }}
        {{- end }}
      ports:
        - protocol: TCP
          port: {{ .port }}
    {{- else }}
    []                   # allowFrom empty: nothing may connect
    {{- end }}
{{- end -}}

{{/*
Spread a backend's replicas across nodes (multi-node clusters). Call with a dict:
  enabled  - the backend's spreadAcrossNodes value
  selector - the backend's rendered selector labels (YAML string)
ScheduleAnyway: prefer different nodes, but never leave a replica Pending because of it.
matchLabelKeys pod-template-hash: count only pods of the same rollout, so old pods of a
rolling update don't skew placement.
*/}}
{{- define "inference.spread" -}}
{{- if .enabled }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- .selector | nindent 8 }}
    matchLabelKeys: [pod-template-hash]
{{- end }}
{{- end -}}
