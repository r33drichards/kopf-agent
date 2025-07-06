{
  description = "Kopf Agent Docker Image";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix.url = "github:nix-community/poetry2nix";
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        pythonEnv = pkgs.python311.withPackages (ps: with ps; [ pip kopf kubernetes python-dotenv ]);
        src = ./.;
      in {
        packages.dockerImage = pkgs.dockerTools.buildImage {
          name = "kopf-agent";
          tag = "latest";
          copyToRoot = pkgs.buildEnv {
            name = "kopf-agent-root";
            paths = [
              (pkgs.writeShellScriptBin "entrypoint" ''
                #!/bin/sh
                exec python3 /app/main.py
              '')
              (pkgs.runCommand "app" {} ''
                mkdir -p $out/app
                cp ${src}/main.py $out/app/
                cp ${src}/pyproject.toml $out/app/ || true
                cp ${src}/requirements.txt $out/app/ || true
              '')
            ];
          };
          config = {
            Cmd = [ "/bin/entrypoint" ];
            WorkingDir = "/app";
          };
        };
        defaultPackage = self.packages.${system}.dockerImage;
      }
    );
}