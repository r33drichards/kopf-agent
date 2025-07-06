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
        lib = pkgs.lib;
        pythonEnv = pkgs.python311.withPackages (ps: with ps; [ pip kopf kubernetes python-dotenv ]);
        entrypoint = pkgs.writeShellScriptBin "entrypoint" ''
          #!${pkgs.bash}/bin/bash
          exec ${pythonEnv}/bin/python3  ${./main.py} "$@"
        '';
      in {
        packages.dockerImage = pkgs.dockerTools.buildImage {
          name = "kopf-agent";
          tag = "latest";
          contents = [ pythonEnv ];
          config = {
            Cmd = [ "${lib.getExe entrypoint}" ];
            WorkingDir = "/app";
          };
        };
        defaultPackage = self.packages.${system}.dockerImage;
      }
    );
}