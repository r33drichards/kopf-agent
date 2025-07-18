add kopf to cluster 
```
kubectl apply -f https://github.com/nolar/kopf/raw/main/peering.yaml
```

create service account for operator
```
kubectl apply -f rbac.yaml
```

deploy operator
```
kubectl apply -f deployment.yaml
```

create crd

```
kubectl apply -f claud-code.crd.yml                  
```

create secret 

```
kubectl create secret generic anthropic-api-key \ 
  --from-literal=ANTHROPIC_API_KEY=sk-ant-api-key
kubectl create secret generic openai-api-key \
  --from-literal=OPENAI_API_KEY=key

```

deploy claud code
```
kubectl apply -f rag.yml
```









