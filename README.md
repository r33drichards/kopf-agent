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

deploy claud code
```
kubectl apply -f cc.yml
```




