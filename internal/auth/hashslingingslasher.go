package auth

// the slash-bringing hasher

import (
	"fmt"

	"golang.org/x/crypto/bcrypt"
)

func HashPass(password string) (string, error) {
	hashword, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	if err != nil {
		fmt.Println(err)
	}
	return string(hashword), err
}

func CheckPassword(hashed string, unhashed string) bool {
	err := bcrypt.CompareHashAndPassword([]byte(hashed), []byte(unhashed))
	return err == nil
}
