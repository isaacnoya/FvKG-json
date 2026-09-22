module MappingCompatibility where

open import Data.Nat using (ℕ)
open import Data.String using (String; toList)
open import Data.List using (List; []; _∷_)
open import Data.Char using (Char)
open import Data.Char.Properties using (_≡ᵇ_) renaming (_≟_ to _≟ᶜ_)
open import Data.Maybe using (Maybe; just; nothing)
open import Relation.Binary.PropositionalEquality using (_≡_; refl;cong;cong₂;sym)
open import Data.Bool using
  (Bool; true; false; _∧_; _∨_)
open import Data.Unit using (⊤; tt)
open import Data.Empty using (⊥; ⊥-elim)
open import Data.Product using (Σ; _×_; _,_;proj₁;proj₂)
open import Data.Sum using (_⊎_; inj₁; inj₂)
open import Data.String.Properties using (_≟_)
open import Relation.Nullary using (yes; no)
open import Data.Bool.Properties using (∧-conicalˡ; ∧-conicalʳ)

infix 2 _↔_

record _↔_ (A B : Set) : Set where
  constructor iff
  field
    forward  : A → B
    backward : B → A
open _↔_
------------------------------------------------------------------------
-- RDF types and datatypes
------------------------------------------------------------------------

-- An RDF term can be either an IRI or a literal.

data RDFType : Set where
  iriType     : RDFType
  literalType : RDFType


-- We initially consider a small collection of RDF datatypes.
-- This can be generalized later.

data Datatype : Set where
  xsdString  : Datatype
  xsdInteger : Datatype
  xsdDate    : Datatype


-- RDF term type used by the compatibility analysis.
-- For literals, rr:termType and rr:datatype are represented together.
-- Set of terms that could be generated.
data RDFTermType : Set where
  iriType     : RDFTermType
  literalType : Datatype → RDFTermType


------------------------------------------------------------------------
-- Concrete RDF terms
------------------------------------------------------------------------

-- RDFTerm corresponds to:
--
--     T_RDF = I ∪ L
--
-- An IRI contains its string representation.
-- A literal contains its lexical value and datatype.

data RDFTerm : Set where
  iri     : String → RDFTerm
  literal : String → Datatype → RDFTerm


------------------------------------------------------------------------
-- Term maps
------------------------------------------------------------------------

-- TermMap corresponds to:
--
--     T_maps = C ∪ U ∪ R
--
-- A template is represented by its invariant: the constant prefix
-- preceding its first reference.
--
-- Both templates and references store the class of RDF term that they
-- generate. A reference stores its reference expression.

data TermMap : Set where
  constantMap  : RDFTerm → TermMap
  referenceMap : String → RDFTermType → TermMap
  templateMap  : String → RDFTermType → TermMap


------------------------------------------------------------------------
-- Elements accepted by TCompatible
------------------------------------------------------------------------

-- TCompatible does not only compare term maps. Its complete domain is:
--
--     T_maps ∪ T_RDF ∪ V
--
-- Therefore, CompatibilityTerm explicitly distinguishes:
--
--   * query variables;
--   * concrete RDF terms;
--   * term maps.

data CompatibilityTerm : Set where
  var     : ℕ → CompatibilityTerm
  rdfTerm : RDFTerm → CompatibilityTerm
  termMap : TermMap → CompatibilityTerm


sameDatatype : Datatype → Datatype → Bool
sameDatatype xsdString xsdString =
  true
sameDatatype xsdInteger xsdInteger =
  true
sameDatatype xsdDate xsdDate =
  true
sameDatatype _ _ =
  false


rdfTermType : RDFTerm → RDFTermType
rdfTermType (iri _) =
  iriType
rdfTermType (literal _ d) =
  literalType d


termMapType : TermMap → RDFTermType
termMapType (constantMap r) =
  rdfTermType r
termMapType (templateMap _ termType) =
  termType
termMapType (referenceMap _ termType) =
  termType


sameRDFTermType : RDFTermType → RDFTermType → Bool
sameRDFTermType iriType iriType =
  true
sameRDFTermType iriType (literalType _) =
  false
sameRDFTermType (literalType _) iriType =
  false
sameRDFTermType (literalType d₁) (literalType d₂) =
  sameDatatype d₁ d₂


invariant : CompatibilityTerm → Maybe String
invariant (var _) =
  nothing
invariant (rdfTerm (iri i)) =
  just i
invariant (rdfTerm (literal l _)) =
  just l
invariant (termMap (constantMap (iri i))) =
  just i
invariant (termMap (constantMap (literal l _))) =
  just l
invariant (termMap (templateMap prefix _)) =
  just prefix
invariant (termMap (referenceMap _ _)) =
  just ""


listPrefix : List Char → List Char → Bool
listPrefix [] _ = true
listPrefix (_ ∷ _ ) [] = false
listPrefix (x ∷ xs) (y ∷ ys) with x ≟ᶜ y
... | yes _ = listPrefix xs ys
... | no _ = false

listPrefix-refl :
  ∀ xs →
  listPrefix xs xs ≡ true
listPrefix-refl [] = refl
listPrefix-refl (x ∷ xs) with x ≟ᶜ x
... | yes _ = listPrefix-refl xs
... | no x≢x = ⊥-elim (x≢x refl)


isPrefixOf : String → String → Bool
isPrefixOf s₁ s₂ = listPrefix (toList s₁) (toList s₂)

listEqual : List Char → List Char → Bool
listEqual [] [] = true
listEqual [] (_ ∷ _) = false
listEqual (_ ∷ _) [] = false
listEqual (x ∷ xs) (y ∷ ys) with x ≡ᵇ y
... | true = listEqual xs ys
... | false = false

sameString : String → String → Bool
sameString s₁ s₂ with s₁ ≟ s₂
... | yes _ = true
... | no _  = false

sameRDFTerm : RDFTerm → RDFTerm → Bool
sameRDFTerm (iri i) (iri i₁) = sameString i i₁
sameRDFTerm (iri _) (literal _ _) = false
sameRDFTerm (literal _ _) (iri _) = false
sameRDFTerm (literal l d) (literal l₂ d₂) = sameString l l₂ ∧ sameDatatype d d₂


rdfLexical : RDFTerm → String
rdfLexical (iri value)       = value
rdfLexical (literal value _) = value


tCompatible : CompatibilityTerm → CompatibilityTerm → Bool
tCompatible (var _) _ =
  true
tCompatible _ (var _) =
  true
tCompatible (termMap (referenceMap _ termType)) (rdfTerm r) =
  sameRDFTermType termType (rdfTermType r)
tCompatible (termMap (referenceMap _ termType)) (termMap m) =
  sameRDFTermType termType (termMapType m)
tCompatible (rdfTerm r) (termMap (referenceMap _ termType)) =
  sameRDFTermType (rdfTermType r) termType
tCompatible (termMap m) (termMap (referenceMap _ termType)) =
  sameRDFTermType (termMapType m) termType
tCompatible (termMap (templateMap p₁ type₁)) (termMap (templateMap p₂ type₂)) =
  sameRDFTermType type₁ type₂ ∧ (isPrefixOf p₁ p₂ ∨ isPrefixOf p₂ p₁)
tCompatible (termMap (templateMap prefix termType)) (rdfTerm r) =
  sameRDFTermType termType (rdfTermType r) ∧ isPrefixOf prefix (rdfLexical r)
tCompatible (rdfTerm r) (termMap (templateMap prefix termType)) =
  sameRDFTermType (rdfTermType r) termType ∧ isPrefixOf prefix (rdfLexical r)
tCompatible (termMap (templateMap prefix termType)) (termMap (constantMap r)) =
  sameRDFTermType termType (rdfTermType r) ∧ isPrefixOf prefix (rdfLexical r)
tCompatible (termMap (constantMap r)) (termMap (templateMap prefix termType)) =
  sameRDFTermType (rdfTermType r) termType ∧ isPrefixOf prefix (rdfLexical r)
tCompatible (rdfTerm r₁) (rdfTerm r₂) =
  sameRDFTerm r₁ r₂
tCompatible (rdfTerm r₁) (termMap (constantMap r₂)) =
  sameRDFTerm r₁ r₂
tCompatible (termMap (constantMap r₁)) (rdfTerm r₂) =
  sameRDFTerm r₁ r₂
tCompatible (termMap (constantMap r₁)) (termMap (constantMap r₂)) =
  sameRDFTerm r₁ r₂


Compatible : CompatibilityTerm → CompatibilityTerm → Set
Compatible t₁ t₂ = tCompatible t₁ t₂ ≡ true  

Prefix : String → String → Set
Prefix s₁ s₂ = isPrefixOf s₁ s₂ ≡ true

prefix-refl :
  ∀ s →
  Prefix s s
prefix-refl s = listPrefix-refl (toList s)


HasType : RDFTermType → RDFTerm → Set
HasType iriType (iri _) = ⊤
HasType iriType (literal _ _) = ⊥
HasType (literalType _) (iri _) = ⊥
HasType (literalType d₁) (literal _ d₂) = d₁ ≡ d₂


Gen : CompatibilityTerm → RDFTerm → Set
Gen (var _) _ = ⊤
Gen (rdfTerm r) r₁ = r ≡ r₁
Gen (termMap (constantMap c)) r = c ≡ r
Gen (termMap (referenceMap _ d)) r = HasType d r
Gen (termMap (templateMap p d)) r = HasType d r × Prefix p (rdfLexical r)

Overlaps : CompatibilityTerm → CompatibilityTerm → Set
Overlaps t₁ t₂ = Σ RDFTerm (λ r → Gen t₁ r × Gen t₂ r)

sameDatatype-correct : ∀ d₁ d₂ → sameDatatype d₁ d₂ ≡ true ↔ d₁ ≡ d₂
sameDatatype-correct xsdString xsdString ._↔_.forward t = refl
sameDatatype-correct xsdString xsdString ._↔_.backward s = refl
sameDatatype-correct xsdString xsdInteger ._↔_.forward = λ ()
sameDatatype-correct xsdString xsdInteger ._↔_.backward = λ ()
sameDatatype-correct xsdString xsdDate ._↔_.forward = λ ()
sameDatatype-correct xsdString xsdDate ._↔_.backward = λ ()
sameDatatype-correct xsdInteger xsdString ._↔_.forward = λ ()
sameDatatype-correct xsdInteger xsdString ._↔_.backward = λ ()
sameDatatype-correct xsdInteger xsdInteger ._↔_.forward t = refl
sameDatatype-correct xsdInteger xsdInteger ._↔_.backward i = refl
sameDatatype-correct xsdInteger xsdDate ._↔_.forward = λ ()
sameDatatype-correct xsdInteger xsdDate ._↔_.backward = λ ()
sameDatatype-correct xsdDate xsdString ._↔_.forward = λ ()
sameDatatype-correct xsdDate xsdString ._↔_.backward = λ ()
sameDatatype-correct xsdDate xsdInteger ._↔_.forward = λ ()
sameDatatype-correct xsdDate xsdInteger ._↔_.backward = λ ()
sameDatatype-correct xsdDate xsdDate ._↔_.forward t = refl
sameDatatype-correct xsdDate xsdDate ._↔_.backward d = refl



sameRDFTermType-correct : ∀ type₁ type₂ → sameRDFTermType type₁ type₂ ≡ true ↔ type₁ ≡ type₂
sameRDFTermType-correct iriType iriType .forward _ = refl
sameRDFTermType-correct iriType iriType .backward _ = refl
sameRDFTermType-correct iriType (literalType x) .forward = λ ()
sameRDFTermType-correct iriType (literalType x) .backward = λ ()
sameRDFTermType-correct (literalType x) iriType .forward = λ ()
sameRDFTermType-correct (literalType x) iriType .backward = λ ()
sameRDFTermType-correct (literalType x) (literalType x₁) .forward s = cong literalType ((sameDatatype-correct x x₁ .forward) s)
sameRDFTermType-correct (literalType x) (literalType .x) .backward refl = sameDatatype-correct x x .backward refl

sameString-correct :
  ∀ s₁ s₂ →
  sameString s₁ s₂ ≡ true
  ↔
  s₁ ≡ s₂

sameString-correct s₁ s₂ with s₁ ≟ s₂
... | yes refl =
  iff
    (λ _ → refl)
    (λ _ → refl)

... | no notEqual =
  iff
    (λ ())
    (λ equal → ⊥-elim (notEqual equal))


and-true-correct :
  ∀ a b →
  (a ∧ b ≡ true) ↔
  (a ≡ true × b ≡ true)

and-true-correct a b .forward p =
  ∧-conicalˡ a b p ,
  ∧-conicalʳ a b p

and-true-correct a b .backward (refl , refl) =
  refl

or-true-correct :
  ∀ a b →
  (a ∨ b ≡ true) ↔
  (a ≡ true ⊎ b ≡ true)

or-true-correct true b .forward p =
  inj₁ refl
or-true-correct false true .forward p =
  inj₂ refl
or-true-correct false false .forward ()
or-true-correct true b .backward p =
  refl
or-true-correct false true .backward p =
  refl
or-true-correct false false .backward (inj₁ ())
or-true-correct false false .backward (inj₂ ())

prefix-overlap :
  ∀ p₁ p₂ →
  (isPrefixOf p₁ p₂ ∨ isPrefixOf p₂ p₁) ≡ true →
  Σ String (λ p → Prefix p₁ p × Prefix p₂ p)
prefix-overlap p₁ p₂ proof =
  prefix-overlap-sum p₁ p₂ (or-true-correct (isPrefixOf p₁ p₂) (isPrefixOf p₂ p₁) .forward proof)
  where
    prefix-overlap-sum :
      ∀ p₁ p₂ →
      (isPrefixOf p₁ p₂ ≡ true ⊎ isPrefixOf p₂ p₁ ≡ true) →
      Σ String (λ p → Prefix p₁ p × Prefix p₂ p)
    prefix-overlap-sum p₁ p₂ (inj₁ p₁-prefix-p₂) = p₂ , (p₁-prefix-p₂ , prefix-refl p₂)
    prefix-overlap-sum p₁ p₂ (inj₂ p₂-prefix-p₁) = p₁ , (prefix-refl p₁ , p₂-prefix-p₁)

prefix-overlap-term :
  ∀ p₁ p₂ →
  (isPrefixOf p₁ p₂ ∨ isPrefixOf p₂ p₁) ≡ true →
  String
prefix-overlap-term p₁ p₂ proof = proj₁ (prefix-overlap p₁ p₂ proof)

prefix-overlap-left :
  ∀ p₁ p₂ →
  (proof : (isPrefixOf p₁ p₂ ∨ isPrefixOf p₂ p₁) ≡ true) →
  Prefix p₁ (prefix-overlap-term p₁ p₂ proof)
prefix-overlap-left p₁ p₂ proof = proj₁ (proj₂ (prefix-overlap p₁ p₂ proof))

prefix-overlap-right :
  ∀ p₁ p₂ →
  (proof : (isPrefixOf p₁ p₂ ∨ isPrefixOf p₂ p₁) ≡ true) →
  Prefix p₂ (prefix-overlap-term p₁ p₂ proof)
prefix-overlap-right p₁ p₂ proof = proj₂ (proj₂ (prefix-overlap p₁ p₂ proof))


sameRDFTerm-correct : ∀ r₁ r₂ → sameRDFTerm r₁ r₂ ≡ true ↔ r₁ ≡ r₂
sameRDFTerm-correct (iri i₁) (iri i₂) .forward s =  cong iri (sameString-correct i₁ i₂ .forward s)
sameRDFTerm-correct (iri i) (iri .i) .backward refl = sameString-correct i i .backward refl
sameRDFTerm-correct (iri _) (literal _ _) .forward = λ ()
sameRDFTerm-correct (iri _) (literal _ _) .backward = λ ()
sameRDFTerm-correct (literal _ _) (iri _) .forward = λ ()
sameRDFTerm-correct (literal _ _) (iri _) .backward = λ ()
sameRDFTerm-correct (literal l₁ d₁) (literal l₂ d₂) .forward s =
  cong₂ literal
    (sameString-correct l₁ l₂ .forward string-equal)
    (sameDatatype-correct d₁ d₂ .forward datatype-equal)
  where
    both-true : sameString l₁ l₂ ≡ true × sameDatatype d₁ d₂ ≡ true
    both-true =
      and-true-correct (sameString l₁ l₂) (sameDatatype d₁ d₂) .forward s

    string-equal : sameString l₁ l₂ ≡ true
    string-equal = proj₁ both-true

    datatype-equal : sameDatatype d₁ d₂ ≡ true
    datatype-equal = proj₂ both-true
sameRDFTerm-correct (literal l d) (literal .l .d) .backward refl =
  and-true-correct (sameString l l) (sameDatatype d d) .backward
   ( sameString-correct l l .backward refl
    , sameDatatype-correct d d .backward refl
    )


tCompatible-sound : ∀ t₁ t₂ → Compatible t₁ t₂ → Overlaps t₁ t₂
tCompatible-sound (var v₁) (var v₂) compatible = iri "", (tt , tt)
tCompatible-sound (var v) (rdfTerm r) compatible = r , (tt , refl)
tCompatible-sound (var v) (termMap (constantMap c)) compatible = c , (tt , refl)
tCompatible-sound (var v) (termMap (referenceMap rm iriType)) compatible = iri "" , (tt , tt)
tCompatible-sound (var v) (termMap (referenceMap rm (literalType x))) compatible = literal "" x , (tt , refl)
tCompatible-sound (var v) (termMap (templateMap tm iriType)) compatible = iri tm , (tt , (tt , prefix-refl tm))
tCompatible-sound (var v) (termMap (templateMap tm (literalType d))) compatible = literal tm d , (tt , (refl , prefix-refl tm))
tCompatible-sound (rdfTerm x) (var x₁) compatible = x , (refl , tt)
tCompatible-sound (rdfTerm x) (rdfTerm x₁) compatible = x₁ , (sameRDFTerm-correct x x₁ .forward compatible , refl)
tCompatible-sound (rdfTerm r) (termMap (constantMap c)) compatible = c , (sameRDFTerm-correct r c .forward compatible , refl)
tCompatible-sound (rdfTerm (iri i)) (termMap (referenceMap rm iriType)) compatible = iri i , (refl , tt)
tCompatible-sound (rdfTerm (literal l₁ d₁)) (termMap (referenceMap rm (literalType d₂))) compatible = literal l₁ d₁ , (refl , sym (sameDatatype-correct d₁ d₂ .forward compatible))
tCompatible-sound (rdfTerm (iri i)) (termMap (templateMap tm iriType)) compatible = iri i , ( refl , (tt , compatible))
tCompatible-sound (rdfTerm (literal l₁ d₁)) (termMap (templateMap tm (literalType d₂))) compatible = literal l₁ d₁ , (refl , (sym (sameDatatype-correct d₁ d₂ .forward (proj₁ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l₁) .forward compatible))) , proj₂ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l₁) .forward compatible)))
tCompatible-sound (termMap (constantMap (iri i))) (var v) compatible = iri i , (refl , tt)
tCompatible-sound (termMap (constantMap (literal l d))) (var v) compatible = literal l d , (refl , tt)
tCompatible-sound (termMap (referenceMap rm iriType)) (var v) compatible = iri "" , (tt , tt)
tCompatible-sound (termMap (referenceMap rm (literalType d))) (var v) compatible = literal "" d , (refl , tt)
tCompatible-sound (termMap (templateMap tm iriType)) (var v) compatible = iri tm , ((tt , prefix-refl tm ) , tt)
tCompatible-sound (termMap (templateMap tm (literalType d))) (var v) compatible = literal tm d , ((refl , prefix-refl tm) , tt)
tCompatible-sound (termMap (constantMap c)) (rdfTerm r) compatible = c , (refl , sym (sameRDFTerm-correct c r .forward compatible))
tCompatible-sound (termMap (referenceMap rm iriType)) (rdfTerm (iri i)) compatible = iri i , (tt , refl)
tCompatible-sound (termMap (referenceMap rm (literalType d₁))) (rdfTerm (literal l d₂)) compatible = literal l d₂ , ( sameDatatype-correct d₁ d₂ .forward compatible , refl)
tCompatible-sound (termMap (templateMap tm iriType)) (rdfTerm (iri i)) compatible = iri i , ((tt , compatible) , refl)
tCompatible-sound (termMap (templateMap tm (literalType d₁))) (rdfTerm (literal l d₂)) compatible = literal l d₂ , ( (sameDatatype-correct d₁ d₂ .forward (proj₁ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l) .forward compatible)) , proj₂ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l) .forward compatible)) , refl )
tCompatible-sound (termMap (constantMap c₁)) (termMap (constantMap c₂)) compatible = c₂ , (sameRDFTerm-correct c₁ c₂ .forward compatible , refl)
tCompatible-sound (termMap (constantMap (iri i))) (termMap (referenceMap rm₁ iriType)) compatible = iri i , (refl , tt )
tCompatible-sound (termMap (constantMap (literal l d₁))) (termMap (referenceMap rm₁ (literalType d₂))) compatible = literal l d₁ , (refl , sym (sameDatatype-correct d₁ d₂ .forward compatible)) 
tCompatible-sound (termMap (constantMap (iri i))) (termMap (templateMap tm iriType)) compatible = iri i , (refl , (tt , compatible))
tCompatible-sound (termMap (constantMap (literal l d₁))) (termMap (templateMap tm (literalType d₂))) compatible = literal l d₁ , (refl , (sym (sameDatatype-correct d₁ d₂ .forward (proj₁ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l) .forward compatible))) , proj₂ ( and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l) .forward compatible)))
tCompatible-sound (termMap (referenceMap rm iriType)) (termMap (constantMap (iri i))) compatible = iri i , (tt , refl)
tCompatible-sound (termMap (referenceMap rm (literalType d₁))) (termMap (constantMap (literal l d₂))) compatible = literal l d₂ , (sameDatatype-correct d₁ d₂ .forward compatible , refl)
tCompatible-sound (termMap (referenceMap rm₁ iriType)) (termMap (referenceMap rm₂ iriType)) compatible = iri "" , (tt , tt)
tCompatible-sound (termMap (referenceMap rm₁ (literalType d₁))) (termMap (referenceMap rm₂ (literalType d₂))) compatible = literal "" d₁ , (refl , sym (sameDatatype-correct d₁ d₂ .forward compatible))
tCompatible-sound (termMap (referenceMap rm iriType)) (termMap (templateMap tm iriType)) compatible = iri tm , (tt , (tt , prefix-refl tm))
tCompatible-sound (termMap (referenceMap rm (literalType d₁))) (termMap (templateMap tm (literalType d₂))) compatible = literal tm d₂ , (sameDatatype-correct d₁ d₂ .forward compatible , (refl , prefix-refl tm))
tCompatible-sound (termMap (templateMap tm iriType)) (termMap (constantMap (iri i))) compatible = iri i , ((tt , compatible) , refl)
tCompatible-sound (termMap (templateMap tm (literalType d₁))) (termMap (constantMap (literal l d₂))) compatible = literal l d₂ , ((sameDatatype-correct d₁ d₂ .forward (proj₁ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l) .forward compatible)) , proj₂ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm l) .forward compatible)) , refl)
tCompatible-sound (termMap (templateMap tm iriType)) (termMap (referenceMap rm₂ iriType)) compatible = iri tm , ((tt , prefix-refl tm) , tt)
tCompatible-sound (termMap (templateMap tm (literalType d₁))) (termMap (referenceMap rm₂ (literalType d₂))) compatible = literal tm d₁ , ((refl , prefix-refl tm) , sym (sameDatatype-correct d₁ d₂ .forward compatible))
tCompatible-sound (termMap (templateMap tm iriType)) (termMap (templateMap tm₂ iriType)) compatible = iri (prefix-overlap-term tm tm₂ (proj₂ (and-true-correct true (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible))) , ((tt , prefix-overlap-left tm tm₂ (proj₂ (and-true-correct true (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible))) , (tt , prefix-overlap-right tm tm₂ (proj₂ (and-true-correct true (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible))))
tCompatible-sound (termMap (templateMap tm (literalType d₁))) (termMap (templateMap tm₂ (literalType d₂))) compatible = literal (prefix-overlap-term tm tm₂ (proj₂ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible))) d₂ , ((sameDatatype-correct d₁ d₂ .forward (proj₁ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible)) , prefix-overlap-left tm tm₂ (proj₂ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible))) , (refl , prefix-overlap-right tm tm₂ (proj₂ (and-true-correct (sameDatatype d₁ d₂) (isPrefixOf tm tm₂ ∨ isPrefixOf tm₂ tm) .forward compatible))))
