package main

import (
	"flag"
	"log"
	"os"
	"os/exec"
)

func run(file string) {
	shell := "pwsh"
	if _, err := exec.LookPath(shell); err != nil {
		shell = "powershell"
	}
	cmd := exec.Command(shell, "-File", file)
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	if err := cmd.Run(); err != nil {
		log.Fatalf("Error running PowerShell script %s: %v", file, err)
		panic(err)
	}
}

func main() {
	ps_script_file := flag.String("file", "", "PowerShell script path to execute")
	flag.Parse()

	run(*ps_script_file)
}
